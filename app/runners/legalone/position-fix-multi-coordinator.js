const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');

function parseArgs(argv) {
  const args = {};
  for (let index = 0; index < argv.length; index += 1) {
    const current = argv[index];
    if (!current.startsWith('--')) continue;
    const key = current.slice(2);
    const next = argv[index + 1];
    if (!next || next.startsWith('--')) {
      args[key] = true;
      continue;
    }
    args[key] = next;
    index += 1;
  }
  return args;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function readJsonFile(filePath, fallback = null) {
  try {
    const raw = fs.readFileSync(filePath, 'utf8').replace(/^\uFEFF/, '');
    return JSON.parse(raw);
  } catch (error) {
    return fallback;
  }
}

function writeJsonFile(filePath, payload) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, JSON.stringify(payload, null, 2));
}

function normalizeSequenceNumber(value) {
  return String(value).padStart(4, '0');
}

function dedupeBySequence(items) {
  const map = new Map();
  for (const item of items || []) {
    const sequenceNumber = normalizeSequenceNumber(item.sequenceNumber || item.seq);
    const attemptNumber = Number(item.attempts || item.attemptNumber || 1);
    const normalized = {
      ...item,
      sequenceNumber,
      attempts: attemptNumber,
    };
    const existing = map.get(sequenceNumber);
    if (!existing || attemptNumber >= Number(existing.attempts || 1)) {
      map.set(sequenceNumber, normalized);
    }
  }
  return [...map.entries()]
    .sort((left, right) => Number(left[0]) - Number(right[0]))
    .map(([, item]) => item);
}

function assignWorkerIndex(sequenceNumber, workerCount) {
  return (Number(sequenceNumber) - 1) % workerCount;
}

function readControlSignal(controlFilePath) {
  try {
    const signal = fs.readFileSync(controlFilePath, 'utf8').trim().toLowerCase();
    if (signal === 'pause' || signal === 'stop') {
      return signal;
    }
  } catch (error) {
    return 'run';
  }
  return 'run';
}

function writeControlSignal(controlFilePath, signal) {
  fs.mkdirSync(path.dirname(controlFilePath), { recursive: true });
  fs.writeFileSync(controlFilePath, signal);
}

function buildWorkerDisplayMetrics(items, runtime, batchSize) {
  const itemMap = new Map(
    (items || []).map((item) => [normalizeSequenceNumber(item.sequenceNumber || item.seq), item]),
  );
  let processedItems = 0;
  let updatedCount = 0;
  let failedCount = 0;
  let retryPendingCount = 0;

  for (const sequenceNumber of runtime.activeSequenceNumbers) {
    const current = itemMap.get(sequenceNumber) || null;
    const baseline = runtime.activeSeedBaseline.get(sequenceNumber) || null;
    const baselineAttempts = Number(baseline?.attempts || baseline?.attemptNumber || 1);
    const currentAttempts = Number(current?.attempts || current?.attemptNumber || 1);
    const processedInCurrentRun = current ? (!baseline || currentAttempts > baselineAttempts) : false;

    if (!processedInCurrentRun) {
      retryPendingCount += 1;
      continue;
    }

    processedItems += 1;
    if (current.status === 'updated') {
      updatedCount += 1;
    } else if (current.status === 'error' || current.status === 'verify_failed') {
      failedCount += 1;
    } else {
      retryPendingCount += 1;
    }
  }

  const totalItems = runtime.activeTotalItems;
  const remainingItems = Math.max(0, totalItems - updatedCount - failedCount);
  const totalBatches = totalItems ? Math.max(1, Math.ceil(totalItems / batchSize)) : 1;
  const currentBatch = totalItems ? Math.min(totalBatches, Math.floor(processedItems / batchSize) + 1) : 1;

  return {
    totalItems,
    processedItems,
    updatedCount,
    failedCount,
    retryPendingCount,
    remainingItems,
    currentBatch,
    totalBatches,
  };
}

function normalizeWorkerStatus(payload, runtime) {
  if (!payload || typeof payload !== 'object') {
    const metrics = buildWorkerDisplayMetrics(runtime.seedItems, runtime, runtime.batchSize);
    return {
      id: runtime.id,
      label: runtime.label,
      state: runtime.process && runtime.process.exitCode == null ? 'starting' : 'stopped',
      totalItems: metrics.totalItems,
      processedItems: metrics.processedItems,
      updatedCount: metrics.updatedCount,
      failedCount: metrics.failedCount,
      retryPendingCount: metrics.retryPendingCount,
      remainingItems: metrics.remainingItems,
      currentBatch: metrics.currentBatch,
      totalBatches: metrics.totalBatches,
      generatedAt: null,
      items: runtime.seedItems,
    };
  }

  const items = dedupeBySequence(payload.items || []);
  const metrics = buildWorkerDisplayMetrics(items, runtime, runtime.batchSize);

  return {
    id: runtime.id,
    label: runtime.label,
    state: payload.state || 'running',
    totalItems: metrics.totalItems,
    processedItems: metrics.processedItems,
    updatedCount: metrics.updatedCount,
    failedCount: metrics.failedCount,
    retryPendingCount: metrics.retryPendingCount,
    remainingItems: metrics.remainingItems,
    currentBatch: metrics.currentBatch,
    totalBatches: metrics.totalBatches,
    generatedAt: payload.generatedAt ?? null,
    items,
  };
}

function aggregateState(workers) {
  const states = workers.map((worker) => worker.state || 'stopped');
  if (states.length === 0) return 'stopped';
  if (states.some((state) => state === 'running')) return 'running';
  if (states.some((state) => state === 'sleeping')) return 'sleeping';
  if (states.every((state) => state === 'paused')) return 'paused';
  if (states.every((state) => state === 'completed')) return 'completed';
  if (states.some((state) => state === 'paused')) return 'running';
  if (states.some((state) => state === 'stopped')) return 'stopped';
  return states[0];
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const configPath = args.config;
  if (!configPath) {
    throw new Error('Use --config <json>');
  }

  const config = readJsonFile(configPath);
  if (!config || !Array.isArray(config.workers) || config.workers.length < 2) {
    throw new Error('Arquivo de config invalido. Informe ao menos 2 workers.');
  }

  const rawInputPath = args['raw-input'];
  const sourceStatusPath = args['source-status'];
  const outputPath = args.output;
  const controlFilePath = args['control-file'];
  const workerScriptPath = args['worker-script'];
  if (!rawInputPath || !sourceStatusPath || !outputPath || !controlFilePath || !workerScriptPath) {
    throw new Error('Informe --raw-input, --source-status, --output, --control-file e --worker-script.');
  }

  const batchSize = Math.max(1, Number(args['batch-size'] || '10'));
  const pauseBetweenBatchesSeconds = Math.max(0, Number(args['pause-between-batches-seconds'] || '0'));
  const maxAttempts = Math.max(1, Number(args['max-attempts'] || '3'));
  const syncIntervalMs = Math.max(1000, Number(args['sync-interval-ms'] || '2000'));
  const shardsRoot = args['shards-root'] || path.join(path.dirname(outputPath), 'multi-workers');
  const workerArtifactsRoot = args['worker-artifacts-root'] || null;
  const nodePath = args['node-path'] || process.execPath;

  const sourceStatus = readJsonFile(sourceStatusPath);
  const sourceItems = dedupeBySequence(sourceStatus?.items || []);
  const sourceSequenceNumbers = new Set(sourceItems.map((item) => normalizeSequenceNumber(item.sequenceNumber || item.seq)));
  const rawItems = readJsonFile(rawInputPath, []);
  if (!Array.isArray(rawItems) || rawItems.length === 0) {
    throw new Error('Arquivo base de entrada invalido.');
  }
  const globalTotalItems =
    sourceItems.length +
    rawItems.filter((item) => !sourceSequenceNumbers.has(normalizeSequenceNumber(item.seq))).length;

  fs.mkdirSync(shardsRoot, { recursive: true });
  writeControlSignal(controlFilePath, readControlSignal(controlFilePath));

  const workerCount = config.workers.length;
  const runtimes = config.workers.map((worker, index) => {
    const shardDir = path.join(shardsRoot, worker.id || `worker-${index + 1}`);
    fs.mkdirSync(shardDir, { recursive: true });

    const seedItems = sourceItems.filter((item) => assignWorkerIndex(item.sequenceNumber, workerCount) === index);
    const seedSequenceNumbers = new Set(seedItems.map((item) => normalizeSequenceNumber(item.sequenceNumber)));
    const inputItems = rawItems
      .filter((item) => assignWorkerIndex(item.seq, workerCount) === index)
      .filter((item) => !seedSequenceNumbers.has(normalizeSequenceNumber(item.seq)));

    const seedPath = path.join(shardDir, 'seed.json');
    const inputPath = path.join(shardDir, 'input.json');
    const statusPath = path.join(shardDir, 'status.json');
    const workerControlPath = path.join(shardDir, 'control.txt');
    const logPath = path.join(shardDir, 'worker.log');
    const errPath = path.join(shardDir, 'worker.err.log');
    const artifactsDir = workerArtifactsRoot ? path.join(workerArtifactsRoot, worker.id || `worker-${index + 1}`) : null;

    writeJsonFile(seedPath, seedItems);
    writeJsonFile(inputPath, inputItems);
    writeControlSignal(workerControlPath, readControlSignal(controlFilePath));
    if (fs.existsSync(statusPath)) {
      fs.unlinkSync(statusPath);
    }
    if (artifactsDir) {
      fs.mkdirSync(artifactsDir, { recursive: true });
    }
    fs.writeFileSync(logPath, '');
    fs.writeFileSync(errPath, '');

    const retryableSeedItems = seedItems.filter(
      (item) =>
        (item.retryPending || item.status === 'error' || item.status === 'verify_failed') &&
        Number(item.attempts || item.attemptNumber || 1) < maxAttempts,
    );
    const activeSeedBaseline = new Map(
      retryableSeedItems.map((item) => [normalizeSequenceNumber(item.sequenceNumber || item.seq), item]),
    );
    const activeSequenceNumbers = [
      ...new Set([
        ...retryableSeedItems.map((item) => normalizeSequenceNumber(item.sequenceNumber || item.seq)),
        ...inputItems.map((item) => normalizeSequenceNumber(item.seq)),
      ]),
    ];

    return {
      id: worker.id || `worker-${index + 1}`,
      label: worker.label || worker.username,
      username: worker.username,
      password: worker.password,
      keyLabel: worker.keyLabel || config.keyLabel || 'MDR Advocacia (NJU69907701)',
      targetPositionId: String(config.targetPositionId || '2'),
      targetPositionText: config.targetPositionText || null,
      terceirizacaoDate: config.terceirizacaoDate || '27/03/2026',
      batchSize,
      seedItems,
      seedCount: seedItems.length,
      seedUpdatedCount: seedItems.filter((item) => item.status === 'updated').length,
      seedFailedCount: seedItems.filter((item) => item.status === 'error' || item.status === 'verify_failed').length,
      seedRetryPendingCount: seedItems.filter((item) => item.status === 'scheduled_retry' || item.retryPending).length,
      totalItems: seedItems.length + inputItems.length,
      activeSeedBaseline,
      activeSequenceNumbers,
      activeTotalItems: activeSequenceNumbers.length,
      seedPath,
      inputPath,
      statusPath,
      controlPath: workerControlPath,
      logPath,
      errPath,
      artifactsDir,
      process: null,
      exitCode: null,
    };
  });

  const startWorker = (runtime) => {
    const stdoutFd = fs.openSync(runtime.logPath, 'a');
    const stderrFd = fs.openSync(runtime.errPath, 'a');
    const child = spawn(
      nodePath,
      [
        workerScriptPath,
        '--input',
        runtime.inputPath,
        '--seed-results',
        runtime.seedPath,
        '--output',
        runtime.statusPath,
        '--control-file',
        runtime.controlPath,
        '--batch-size',
        String(batchSize),
        '--pause-between-batches-seconds',
        String(pauseBetweenBatchesSeconds),
        '--max-attempts',
        String(maxAttempts),
        ...(runtime.artifactsDir ? ['--artifacts-dir', runtime.artifactsDir] : []),
      ],
      {
        cwd: path.dirname(workerScriptPath),
        env: {
          ...process.env,
          LEGALONE_WEB_USERNAME: runtime.username,
          LEGALONE_WEB_PASSWORD: runtime.password,
          LEGALONE_WEB_KEY_LABEL: runtime.keyLabel,
          LEGALONE_TARGET_POSITION_ID: runtime.targetPositionId,
          LEGALONE_TERCEIRIZACAO_DATE: runtime.terceirizacaoDate,
          ...(runtime.targetPositionText ? { LEGALONE_TARGET_POSITION_TEXT: runtime.targetPositionText } : {}),
        },
        stdio: ['ignore', stdoutFd, stderrFd],
      },
    );
    runtime.process = child;
    child.on('exit', (code) => {
      runtime.exitCode = code;
    });
  };

  for (const runtime of runtimes) {
    startWorker(runtime);
  }

  while (true) {
    const topSignal = readControlSignal(controlFilePath);
    for (const runtime of runtimes) {
      writeControlSignal(runtime.controlPath, topSignal === 'pause' ? 'pause' : topSignal === 'stop' ? 'stop' : 'run');
    }

    const workerStatuses = runtimes.map((runtime) => {
      const payload = readJsonFile(runtime.statusPath);
      return normalizeWorkerStatus(payload, runtime);
    });
    const mergedItems = dedupeBySequence(workerStatuses.flatMap((worker) => worker.items || []));
    const totalItems = globalTotalItems;
    const updatedCount = mergedItems.filter((item) => item.status === 'updated').length;
    const failedCount = mergedItems.filter((item) => item.status === 'error' || item.status === 'verify_failed').length;
    const retryPendingCount = mergedItems.filter((item) => item.status === 'scheduled_retry' || item.retryPending).length;
    const processedItems = mergedItems.length;
    const remainingItems = Math.max(0, totalItems - updatedCount - failedCount);

    const aggregatePayload = {
      generatedAt: new Date().toISOString(),
      state: aggregateState(workerStatuses),
      batchSize: null,
      currentBatch: null,
      totalBatches: null,
      sleepUntil: null,
      controlFile: controlFilePath,
      totalItems,
      processedItems,
      updatedCount,
      failedCount,
      retryPendingCount,
      remainingItems,
      activeQueueType: workerStatuses.some((worker) => worker.state === 'running' && worker.retryPendingCount > 0) ? 'mixed' : null,
      retryPass: null,
      maxAttempts,
      workers: workerStatuses.map((worker) => ({
        id: worker.id,
        label: worker.label,
        state: worker.state,
        total_items: worker.totalItems,
        processed_items: worker.processedItems,
        updated_count: worker.updatedCount,
        failed_count: worker.failedCount,
        retry_pending_count: worker.retryPendingCount,
        remaining_items: worker.remainingItems,
        current_batch: worker.currentBatch,
        total_batches: worker.totalBatches,
        generated_at: worker.generatedAt,
      })),
      items: mergedItems,
    };
    writeJsonFile(outputPath, aggregatePayload);

    const allExited = runtimes.every((runtime) => runtime.process && runtime.exitCode != null);
    const done = remainingItems === 0 && retryPendingCount === 0;
    if (done || allExited || topSignal === 'stop') {
      const finalState = done ? 'completed' : topSignal === 'stop' ? 'stopped' : aggregatePayload.state;
      writeJsonFile(outputPath, {
        ...aggregatePayload,
        generatedAt: new Date().toISOString(),
        state: finalState,
      });
      break;
    }

    await sleep(syncIntervalMs);
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
