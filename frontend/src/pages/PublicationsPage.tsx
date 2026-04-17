/**
 * PublicationsPage — Busca, revisão e agendamento de publicações judiciais
 *
 * Fluxo:
 *   1. Operador dispara busca (período + escritório + tipo)
 *   2. Motor busca, enriquece, classifica e monta proposta de tarefa
 *   3. Operador revisa processos agrupados, confirma ou edita
 *   4. Ao confirmar → tarefa criada no Legal One
 */

import { useEffect, useState, useCallback } from "react";
import {
  AlertCircle,
  BarChart3,
  BookOpen,
  Building2,
  Calendar,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Clock,
  Eye,
  EyeOff,
  ExternalLink,
  FileDown,
  Filter,
  Layers,
  Link2,
  Loader2,
  MessageSquareWarning,
  Newspaper,
  Play,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  Send,
  Settings,
  ThumbsDown,
  XCircle,
} from "lucide-react";
import { Link } from "react-router-dom";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import { useToast } from "@/hooks/use-toast";
import { apiFetch } from "@/lib/api-client";

const API = "/api/v1/publications";
const API_V1 = "/api/v1";

// ─── Types ──────────────────────────────────────────────────────────────────

interface Statistics {
  total_records: number;
  by_status: { novo: number; classificado: number; agendado: number; ignorado: number; erro: number };
  total_searches: number;
  last_search: SearchItem | null;
}

interface SearchItem {
  id: number;
  status: string;
  date_from: string;
  date_to: string | null;
  origin_type: string;
  office_filter: string | null;
  total_found: number;
  total_new: number;
  total_duplicate: number;
  progress_step: string | null;
  progress_detail: string | null;
  progress_pct: number | null;
  requested_by_email: string | null;
  error_message: string | null;
  created_at: string | null;
  finished_at: string | null;
}

interface Classification {
  categoria: string;
  subcategoria: string;
  polo: "ativo" | "passivo" | "ambos";
  confianca?: string;
  justificativa?: string;
  audiencia_data?: string | null;
  audiencia_hora?: string | null;
  audiencia_link?: string | null;
}

interface PublicationRecord {
  id: number;
  search_id: number;
  legal_one_update_id: number;
  origin_type: string | null;
  update_type_id: number | null;
  description_preview: string;
  description?: string;
  notes?: string;
  publication_date: string | null;
  creation_date: string | null;
  linked_lawsuit_id: number | null;
  linked_lawsuit_cnj: string | null;
  linked_office_id: number | null;
  status: string;
  category: string | null;
  subcategory: string | null;
  polo: "ativo" | "passivo" | "ambos" | null;
  audiencia_data: string | null;
  audiencia_hora: string | null;
  audiencia_link: string | null;
  natureza_processo: string | null;
  classifications: Classification[] | null;
  created_at: string | null;
  raw_relationships?: any;
}

interface PublicationBatch {
  id: number;
  anthropic_batch_id: string | null;
  status: "ENVIADO" | "EM_PROCESSAMENTO" | "PRONTO" | "APLICADO" | "FALHA" | "CANCELADO";
  anthropic_status: string | null;
  total_records: number;
  succeeded_count: number;
  errored_count: number;
  expired_count: number;
  canceled_count: number;
  model_used: string | null;
  requested_by_email: string | null;
  error_message: string | null;
  created_at: string | null;
  submitted_at: string | null;
  ended_at: string | null;
  applied_at: string | null;
  error_details: Record<string, string> | null;
}

interface SuggestedResponsible {
  id: number;
  name: string | null;
  email: string | null;
  source: string;
}

interface ProposedTask {
  description: string;
  priority: string;
  startDateTime: string;
  endDateTime: string;
  typeId: number;
  subTypeId: number;
  responsibleOfficeId: number | null;
  participants: any[];
  notes: string | null;
  template_name?: string;
  suggested_responsible?: SuggestedResponsible | null;
}

interface GroupedRecord {
  lawsuit_id: number | null;
  lawsuit_cnj: string | null;
  office_id: number | null;
  records: PublicationRecord[];
  proposed_task: ProposedTask | null;
  proposed_tasks: ProposedTask[];
  classifications: Classification[];
}

interface GroupedResponse {
  total_groups: number;
  total_records?: number;
  offset: number;
  limit: number;
  groups: GroupedRecord[];
}

interface Office {
  id: number;
  external_id: number;
  name: string;
  path: string;
}

interface TaskSubtype {
  external_id: number;
  name: string;
}

interface TaskType {
  external_id: number;
  name: string;
  subtypes: TaskSubtype[];
}

interface AppUser {
  external_id: number;
  name: string;
  email: string | null;
}

/** Retorna o label completo do escritório: usa path se disponível, senão name */
const officeLabel = (o: Office) => o.path || o.name;

// ─── Helpers ────────────────────────────────────────────────────────────────

const statusColor = (status: string): "default" | "secondary" | "destructive" | "outline" => {
  const map: Record<string, any> = {
    CONCLUIDO: "default", EXECUTANDO: "secondary", FALHA: "destructive", CANCELADO: "outline",
    NOVO: "secondary", CLASSIFICADO: "default", AGENDADO: "default", IGNORADO: "outline", ERRO: "destructive",
    DESCARTADO_DUPLICADA: "outline", DESCARTADO_OBSOLETA: "outline",
  };
  return map[status] || "secondary";
};

const formatDate = (iso: string | null) => {
  if (!iso) return "-";
  try { return new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }); }
  catch { return iso; }
};

const formatDateShort = (iso: string | null) => {
  if (!iso) return "-";
  try { return new Date(iso).toLocaleDateString("pt-BR"); }
  catch { return iso; }
};

/** Badge label/color for the polo tag (ativo/passivo/ambos). */
const poloLabel = (polo: string | null | undefined) => {
  if (!polo) return null;
  const map: Record<string, { label: string; className: string }> = {
    ativo: { label: "Polo Ativo", className: "bg-emerald-100 text-emerald-800 border-emerald-300" },
    passivo: { label: "Polo Passivo", className: "bg-rose-100 text-rose-800 border-rose-300" },
    ambos: { label: "Ambos os Polos", className: "bg-sky-100 text-sky-800 border-sky-300" },
  };
  return map[polo] || null;
};

/**
 * Extrai UF (ou região) a partir do CNJ. Formato: NNNNNNN-DD.AAAA.J.TR.OOOO
 *   J=8 (Justiça Estadual) → TR identifica o TJ, mapeado para UF.
 *   J=4 (Justiça Federal) → TR é a região (TRF1..TRF6).
 *   J=7 (Justiça do Trabalho) → TR é a região (TRT1..TRT24).
 * Retorna null se o padrão não bater.
 */
const ufFromCnj = (cnj: string | null | undefined): string | null => {
  if (!cnj) return null;
  const digits = cnj.replace(/\D/g, "");
  if (digits.length !== 20) return null;
  // Posições no CNJ sem pontuação: 0-6 num, 7-8 dv, 9-12 ano, 13 J, 14-15 TR, 16-19 origem
  const j = digits.charAt(13);
  const tr = digits.substring(14, 16);
  const ESTADUAL: Record<string, string> = {
    "01": "AC", "02": "AL", "03": "AP", "04": "AM", "05": "BA", "06": "CE",
    "07": "DF", "08": "ES", "09": "GO", "10": "MA", "11": "MT", "12": "MS",
    "13": "MG", "14": "PA", "15": "PB", "16": "PR", "17": "PE", "18": "PI",
    "19": "RJ", "20": "RN", "21": "RS", "22": "RO", "23": "RR", "24": "SC",
    "25": "SP", "26": "SE", "27": "TO",
  };
  if (j === "8") return ESTADUAL[tr] ?? null;
  if (j === "4") return `TRF${parseInt(tr, 10) || tr}`;
  if (j === "7") return `TRT${parseInt(tr, 10) || tr}`;
  if (j === "5") return `JME${parseInt(tr, 10) || tr}`; // Justiça Militar
  if (j === "6") return `TRE-${ESTADUAL[tr] ?? tr}`;    // Justiça Eleitoral
  return null;
};

const batchStatusColor = (status: string): "default" | "secondary" | "destructive" | "outline" => {
  const map: Record<string, any> = {
    ENVIADO: "secondary",
    EM_PROCESSAMENTO: "secondary",
    PRONTO: "default",
    APLICADO: "default",
    FALHA: "destructive",
    CANCELADO: "outline",
  };
  return map[status] || "secondary";
};

const batchStatusLabel = (status: string): string => {
  const map: Record<string, string> = {
    ENVIADO: "Enviado",
    EM_PROCESSAMENTO: "Em processamento",
    PRONTO: "Pronto",
    APLICADO: "Aplicado",
    FALHA: "Falha",
    CANCELADO: "Cancelado",
  };
  return map[status] || status;
};

// ─── Component ──────────────────────────────────────────────────────────────

const PublicationsPage = () => {
  const { toast } = useToast();

  const [offices, setOffices] = useState<Office[]>([]);
  const [taskTypes, setTaskTypes] = useState<TaskType[]>([]);
  const [appUsers, setAppUsers] = useState<AppUser[]>([]);
  const [taxonomy, setTaxonomy] = useState<Record<string, string[]>>({});
  const [reclassifyingGroup, setReclassifyingGroup] = useState<string | null>(null);
  const [stats, setStats] = useState<Statistics | null>(null);

  // Search form
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [originType, setOriginType] = useState("OfficialJournalsCrawler");
  const [searchOfficeId, setSearchOfficeId] = useState<string>("");
  const [searchOnlyUnlinked, setSearchOnlyUnlinked] = useState(false);
  const [indexStatus, setIndexStatus] = useState<{
    total_ids: number;
    in_progress: boolean;
    progress_pct: number;
    last_full_sync_at: string | null;
    last_sync_status: string | null;
    is_fresh: boolean;
  } | null>(null);
  const [isSearching, setIsSearching] = useState(false);

  // Search history
  const [searches, setSearches] = useState<SearchItem[]>([]);
  const [searchesExpanded, setSearchesExpanded] = useState(false);

  // Grouped records
  const [grouped, setGrouped] = useState<GroupedResponse | null>(null);
  const [filterStatus, setFilterStatus] = useState<string>("");
  const [filterOffice, setFilterOffice] = useState<string>("");
  const [filterDateFrom, setFilterDateFrom] = useState<string>("");
  const [filterDateTo, setFilterDateTo] = useState<string>("");
  const [filterCategory, setFilterCategory] = useState<string>("");
  const [filterUf, setFilterUf] = useState<string>("");
  const [filterVinculo, setFilterVinculo] = useState<string>("");
  const [groupPage, setGroupPage] = useState(0);
  const GROUP_PAGE_SIZE = 20;

  // Detail dialog
  const [selectedRecord, setSelectedRecord] = useState<PublicationRecord | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);

  // Schedule dialog
  const [scheduleGroup, setScheduleGroup] = useState<GroupedRecord | null>(null);
  const [scheduleOpen, setScheduleOpen] = useState(false);
  const [editedPayloads, setEditedPayloads] = useState<Partial<ProposedTask>[]>([]);
  const [scheduling, setScheduling] = useState(false);

  // Bulk selection de grupos (Processos com Publicações)
  const [selectedGroupKeys, setSelectedGroupKeys] = useState<Set<string>>(new Set());
  const [bulkProcessing, setBulkProcessing] = useState(false);

  // Batch classification
  const [batches, setBatches] = useState<PublicationBatch[]>([]);
  const [batchesExpanded, setBatchesExpanded] = useState(true);
  const [submittingBatch, setSubmittingBatch] = useState(false);
  const [refreshingBatchId, setRefreshingBatchId] = useState<number | null>(null);
  const [applyingBatchId, setApplyingBatchId] = useState<number | null>(null);
  const [batchOfficeId, setBatchOfficeId] = useState<string>("");
  const [batchLimit, setBatchLimit] = useState<string>("");
  const [batchOnlyUnlinked, setBatchOnlyUnlinked] = useState(false);
  const [retryingBatchId, setRetryingBatchId] = useState<number | null>(null);
  const [errorDetailsBatchId, setErrorDetailsBatchId] = useState<number | null>(null);
  const [removedTaskIndices, setRemovedTaskIndices] = useState<Set<number>>(new Set());

  // Feedback explícito (thumbs-down)
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [feedbackRecord, setFeedbackRecord] = useState<PublicationRecord | null>(null);
  const [feedbackErrorType, setFeedbackErrorType] = useState<string>("category");
  const [feedbackCategory, setFeedbackCategory] = useState<string>("");
  const [feedbackSubcategory, setFeedbackSubcategory] = useState<string>("");
  const [feedbackPolo, setFeedbackPolo] = useState<string>("");
  const [feedbackNatureza, setFeedbackNatureza] = useState<string>("");
  const [feedbackNote, setFeedbackNote] = useState<string>("");
  const [submittingFeedback, setSubmittingFeedback] = useState(false);

  const [error, setError] = useState<string | null>(null);

  // ─── Duplicate divergences ───────────────────────────────────────────
  const [showDuplicates, setShowDuplicates] = useState(false);
  const [loadingDuplicates, setLoadingDuplicates] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [savedFilters, setSavedFilters] = useState<any[]>([]);
  const [isSaveFilterDialogOpen, setIsSaveFilterDialogOpen] = useState(false);
  const [filterName, setFilterName] = useState("");
  const [isFilterDefault, setIsFilterDefault] = useState(false);
  const [isSavingFilter, setIsSavingFilter] = useState(false);
  const [duplicates, setDuplicates] = useState<{
    total: number;
    divergences: Array<{
      legal_one_update_id: number;
      original: PublicationRecord;
      duplicate: PublicationRecord;
    }>;
  } | null>(null);

  // ─── Data loading ────────────────────────────────────────────────────

  const loadOffices = useCallback(async () => {
    try {
      const res = await apiFetch("/api/v1/offices");
      if (res.ok) setOffices(await res.json());
    } catch { /* ignore */ }
  }, []);

  const loadTaskMeta = useCallback(async () => {
    try {
      const [ttRes, usrRes, taxRes] = await Promise.all([
        apiFetch("/api/v1/task-templates/meta/task-types"),
        apiFetch("/api/v1/task-templates/meta/users"),
        apiFetch("/api/v1/publications/classification-taxonomy"),
      ]);
      if (ttRes.ok) setTaskTypes(await ttRes.json());
      if (usrRes.ok) setAppUsers(await usrRes.json());
      if (taxRes.ok) {
        const data = await taxRes.json();
        setTaxonomy(data.taxonomy || {});
      }
    } catch { /* ignore */ }
  }, []);

  const loadStats = useCallback(async () => {
    try {
      const res = await apiFetch(`${API}/statistics`);
      if (res.ok) setStats(await res.json());
    } catch { /* ignore */ }
  }, []);

  const loadSearches = useCallback(async () => {
    try {
      const res = await apiFetch(`${API}/searches?limit=15`);
      if (res.ok) setSearches(await res.json());
    } catch { /* ignore */ }
  }, []);

  const loadDuplicates = useCallback(async () => {
    setLoadingDuplicates(true);
    try {
      const res = await apiFetch(`${API}/records/duplicate-divergences?limit=50`);
      if (res.ok) setDuplicates(await res.json());
    } catch { /* ignore */ }
    finally { setLoadingDuplicates(false); }
  }, []);

  const loadGrouped = useCallback(async (
    page = 0, status = "", officeId = "", dateFrom = "", dateTo = "", category = "", ufParam = "", vinculoParam = "",
  ) => {
    try {
      let url = `${API}/records/grouped?limit=${GROUP_PAGE_SIZE}&offset=${page * GROUP_PAGE_SIZE}`;
      if (status) url += `&status=${status}`;
      if (officeId) url += `&linked_office_id=${officeId}`;
      if (dateFrom) url += `&date_from=${dateFrom}`;
      if (dateTo) url += `&date_to=${dateTo}`;
      if (category) url += `&category=${encodeURIComponent(category)}`;
      if (ufParam) url += `&uf=${encodeURIComponent(ufParam)}`;
      if (vinculoParam) url += `&vinculo=${vinculoParam}`;
      const res = await apiFetch(url);
      if (res.ok) setGrouped(await res.json());
    } catch { /* ignore */ }
  }, []);

  const handleExportExcel = async () => {
    if (isExporting) return;
    setIsExporting(true);
    try {
      const params = new URLSearchParams();
      if (filterStatus) params.set("status", filterStatus);
      if (filterOffice) params.set("linked_office_id", filterOffice);
      if (filterDateFrom) params.set("date_from", filterDateFrom);
      if (filterDateTo) params.set("date_to", filterDateTo);
      if (filterCategory) params.set("category", filterCategory);
      if (filterUf) params.set("uf", filterUf);
      const qs = params.toString();
      const url = `${API}/records/grouped/export${qs ? `?${qs}` : ""}`;

      const res = await apiFetch(url);
      if (!res.ok) {
        throw new Error(`Falha ao exportar (HTTP ${res.status}).`);
      }
      const blob = await res.blob();

      // Extrai o filename do Content-Disposition quando presente,
      // senão usa um nome padrão com timestamp local.
      let filename = `publicacoes-${new Date()
        .toISOString()
        .replace(/[-:T]/g, "")
        .slice(0, 14)}.xlsx`;
      const disposition = res.headers.get("content-disposition") || "";
      const match = disposition.match(/filename="?([^";]+)"?/i);
      if (match?.[1]) filename = match[1];

      const blobUrl = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = blobUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(blobUrl);
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : "Erro ao exportar Excel.");
    } finally {
      setIsExporting(false);
    }
  };

  const loadRecordDetail = async (id: number) => {
    try {
      const res = await apiFetch(`${API}/records/${id}`);
      if (res.ok) { setSelectedRecord(await res.json()); setDetailOpen(true); }
    } catch { /* ignore */ }
  };

  const loadBatches = useCallback(async () => {
    try {
      const res = await apiFetch(`${API}/classify-batch?limit=50`);
      if (res.ok) setBatches(await res.json());
    } catch { /* ignore */ }
  }, []);

  const loadSavedFilters = useCallback(async () => {
    try {
      const res = await apiFetch("/api/v1/me/saved-filters?module=publications");
      if (res.ok) {
        const data = await res.json();
        setSavedFilters(Array.isArray(data) ? data : data.items || []);
      }
    } catch (err) {
      console.error("Erro ao carregar filtros salvos:", err);
    }
  }, []);

  const handleSaveFilter = async () => {
    if (!filterName.trim()) {
      toast({ title: "Erro", description: "Digite um nome para o filtro.", variant: "destructive" });
      return;
    }
    setIsSavingFilter(true);
    try {
      const filtersJson = {
        status: filterStatus,
        office: filterOffice,
        dateFrom: filterDateFrom,
        dateTo: filterDateTo,
        category: filterCategory,
        uf: filterUf,
        vinculo: filterVinculo,
      };
      const res = await apiFetch("/api/v1/me/saved-filters", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: filterName,
          module: "publications",
          filters_json: filtersJson,
          is_default: isFilterDefault,
        }),
      });
      if (!res.ok) throw new Error("Falha ao salvar filtro");
      toast({ title: "Sucesso", description: "Filtro salvo com sucesso." });
      setIsSaveFilterDialogOpen(false);
      setFilterName("");
      setIsFilterDefault(false);
      loadSavedFilters();
    } catch (err: any) {
      toast({ title: "Erro", description: err.message, variant: "destructive" });
    } finally {
      setIsSavingFilter(false);
    }
  };

  const handleApplySavedFilter = (filter: any) => {
    try {
      const parsed = typeof filter.filters_json === 'string' ? JSON.parse(filter.filters_json) : filter.filters_json;
      handleFilterChange(parsed.status || "", parsed.office || "", parsed.dateFrom, parsed.dateTo, parsed.category, parsed.uf || "", parsed.vinculo || "");
    } catch (err) {
      toast({ title: "Erro", description: "Não foi possível aplicar o filtro.", variant: "destructive" });
    }
  };

  const handleDeleteFilter = async (filterId: number) => {
    try {
      const res = await apiFetch(`/api/v1/me/saved-filters/${filterId}`, { method: "DELETE" });
      if (!res.ok) throw new Error("Falha ao deletar filtro");
      toast({ title: "Sucesso", description: "Filtro deletado." });
      loadSavedFilters();
    } catch (err: any) {
      toast({ title: "Erro", description: err.message, variant: "destructive" });
    }
  };

  useEffect(() => {
    loadOffices();
    loadTaskMeta();
    loadStats();
    loadSearches();
    loadGrouped(0, "", "", "", "", "", "", "");
    loadBatches();
    loadSavedFilters();
  }, []);

  // ─── Office Lawsuit Index ─────────────────────────────────────────────
  const loadIndexStatus = useCallback(async (officeId: string) => {
    if (!officeId) { setIndexStatus(null); return; }
    try {
      const res = await apiFetch(`${API_V1}/offices/${officeId}/lawsuit-index`);
      if (res.ok) setIndexStatus(await res.json());
    } catch { /* ignore */ }
  }, []);

  const handleSyncIndex = async (forceFull: boolean = false) => {
    if (!searchOfficeId) return;
    try {
      const res = await apiFetch(
        `${API_V1}/offices/${searchOfficeId}/lawsuit-index/sync?force_full=${forceFull}`,
        { method: "POST" }
      );
      if (res.ok) setIndexStatus(await res.json());
    } catch (err: any) {
      toast({ title: "Erro", description: err.message, variant: "destructive" });
    }
  };

  useEffect(() => {
    loadIndexStatus(searchOfficeId);
  }, [searchOfficeId, loadIndexStatus]);

  useEffect(() => {
    if (!searchOfficeId || !indexStatus?.in_progress) return;
    const t = setInterval(() => loadIndexStatus(searchOfficeId), 3000);
    return () => clearInterval(t);
  }, [searchOfficeId, indexStatus?.in_progress, loadIndexStatus]);

  // ─── Polling de progresso de busca ativa ─────────────────────────────
  const activeSearch = searches.find((s) => s.status === "EXECUTANDO");
  useEffect(() => {
    if (!activeSearch) return;
    const t = setInterval(async () => {
      await loadSearches();
    }, 2000);
    return () => {
      clearInterval(t);
      // Quando polling para (busca terminou), recarrega dados
      loadStats();
      loadGrouped(groupPage, filterStatus, filterOffice, filterDateFrom, filterDateTo, filterCategory, filterUf, filterVinculo);
    };
  }, [activeSearch?.id]);

  // ─── Actions ─────────────────────────────────────────────────────────

  const handleSearch = async () => {
    if (!dateFrom) { setError("Data inicial é obrigatória."); return; }
    setIsSearching(true);
    setError(null);
    try {
      const payload = {
        date_from: new Date(dateFrom).toISOString(),
        date_to: dateTo ? new Date(dateTo).toISOString() : null,
        origin_type: originType,
        responsible_office_id: searchOfficeId ? parseInt(searchOfficeId) : null,
        auto_classify: false,
        only_unlinked: searchOnlyUnlinked,
      };
      const res = await apiFetch(`${API}/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Erro ao iniciar busca");
      }
      toast({ title: "Busca iniciada", description: "Acompanhe o progresso no histórico." });
      [3000, 8000, 15000, 30000].forEach((delay) => {
        setTimeout(() => { loadSearches(); loadStats(); loadGrouped(0, filterStatus, filterOffice, filterDateFrom, filterDateTo, filterCategory, filterUf, filterVinculo); }, delay);
      });
    } catch (err: any) {
      setError(err.message);
    } finally {
      setIsSearching(false);
    }
  };

  const handleFilterChange = (
    status: string, officeId: string, dateFrom?: string, dateTo?: string, category?: string, ufParam?: string, vinculoParam?: string,
  ) => {
    setFilterStatus(status);
    setFilterOffice(officeId);
    if (dateFrom !== undefined) setFilterDateFrom(dateFrom);
    if (dateTo !== undefined) setFilterDateTo(dateTo);
    if (category !== undefined) setFilterCategory(category);
    if (ufParam !== undefined) setFilterUf(ufParam);
    if (vinculoParam !== undefined) setFilterVinculo(vinculoParam);
    const df = dateFrom ?? filterDateFrom;
    const dt = dateTo ?? filterDateTo;
    const cat = category ?? filterCategory;
    const uf = ufParam ?? filterUf;
    const vin = vinculoParam ?? filterVinculo;
    setGroupPage(0);
    setSelectedGroupKeys(new Set());
    loadGrouped(0, status, officeId, df, dt, cat, uf, vin);
  };

  const handleGroupPageChange = (newPage: number) => {
    setGroupPage(newPage);
    setSelectedGroupKeys(new Set());
    loadGrouped(newPage, filterStatus, filterOffice, filterDateFrom, filterDateTo, filterCategory, filterUf, filterVinculo);
  };

  const handleIgnoreRecord = async (recordId: number) => {
    try {
      await apiFetch(`${API}/records/${recordId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "IGNORADO" }),
      });
      toast({ title: "Registro ignorado" });
      loadGrouped(groupPage, filterStatus, filterOffice, filterDateFrom, filterDateTo, filterCategory, filterUf, filterVinculo);
      loadStats();
    } catch { /* ignore */ }
  };

  const handleReclassifyGroup = async (
    groupKey: string,
    recordIds: number[],
    value: string,
  ) => {
    // `value` formato: "Categoria" ou "Categoria|||Subcategoria"
    const [category, subcategory] = value.split("|||");
    if (!category) return;
    setReclassifyingGroup(groupKey);
    try {
      const res = await apiFetch(`${API}/records/reclassify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          record_ids: recordIds,
          category,
          subcategory: subcategory || null,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Falha ao reclassificar.");
      }
      toast({
        title: "Reclassificado",
        description: `${category}${subcategory ? " → " + subcategory : ""} aplicado a ${recordIds.length} publicação(ões). Proposta de tarefa atualizada.`,
      });
      loadGrouped(groupPage, filterStatus, filterOffice, filterDateFrom, filterDateTo, filterCategory, filterUf, filterVinculo);
      loadStats();
    } catch (err: any) {
      toast({ title: "Erro", description: err.message, variant: "destructive" });
    } finally {
      setReclassifyingGroup(null);
    }
  };

  // ─── Feedback explícito (thumbs-down) ─────────────────────────────────
  const openFeedback = (rec: PublicationRecord) => {
    setFeedbackRecord(rec);
    setFeedbackErrorType("category");
    setFeedbackCategory(rec.category || "");
    setFeedbackSubcategory(rec.subcategory || "");
    setFeedbackPolo(rec.polo || "");
    setFeedbackNatureza(rec.natureza_processo || "");
    setFeedbackNote("");
    setFeedbackOpen(true);
  };

  const handleSubmitFeedback = async () => {
    if (!feedbackRecord) return;
    if (!feedbackCategory) {
      toast({ title: "Erro", description: "Selecione a categoria correta.", variant: "destructive" });
      return;
    }
    setSubmittingFeedback(true);
    try {
      const res = await apiFetch(`${API}/records/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          record_id: feedbackRecord.id,
          error_type: feedbackErrorType,
          corrected_category: feedbackCategory,
          corrected_subcategory: feedbackSubcategory || null,
          corrected_polo: feedbackPolo || null,
          corrected_natureza: feedbackNatureza || null,
          user_note: feedbackNote || null,
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Erro ao enviar feedback.");
      }
      toast({ title: "Feedback registrado", description: "Obrigado! O classificador vai aprender com essa correção." });
      setFeedbackOpen(false);
      loadGrouped(groupPage, filterStatus, filterOffice, filterDateFrom, filterDateTo, filterCategory, filterUf, filterVinculo);
    } catch (err: any) {
      toast({ title: "Erro", description: err.message, variant: "destructive" });
    } finally {
      setSubmittingFeedback(false);
    }
  };

  const handleRefreshAll = () => {
    loadStats(); loadSearches(); loadGrouped(groupPage, filterStatus, filterOffice, filterDateFrom, filterDateTo, filterCategory, filterUf, filterVinculo); loadBatches();
  };

  // ─── Batch classification ────────────────────────────────────────────

  const handleSubmitBatch = async () => {
    setSubmittingBatch(true);
    try {
      const payload: Record<string, unknown> = {};
      if (batchOfficeId) payload.linked_office_id = parseInt(batchOfficeId);
      if (batchLimit) {
        const parsed = parseInt(batchLimit);
        if (!Number.isNaN(parsed) && parsed > 0) payload.limit = parsed;
      }
      if (batchOnlyUnlinked) payload.only_unlinked = true;
      const res = await apiFetch(`${API}/classify-batch/submit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Erro ao enviar lote");
      }
      const created = await res.json();
      toast({
        title: "Lote enviado à Anthropic",
        description: `Batch #${created.id} com ${created.total_records} publicações. Aguarde processamento.`,
      });
      loadBatches();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      toast({ title: "Erro ao enviar lote", description: msg, variant: "destructive" });
    } finally {
      setSubmittingBatch(false);
    }
  };

  const handleRefreshBatch = async (batchId: number) => {
    setRefreshingBatchId(batchId);
    try {
      const res = await apiFetch(`${API}/classify-batch/${batchId}/refresh`, { method: "POST" });
      if (!res.ok) throw new Error("Falha ao atualizar status");
      await loadBatches();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      toast({ title: "Erro", description: msg, variant: "destructive" });
    } finally {
      setRefreshingBatchId(null);
    }
  };

  const handleApplyBatch = async (batchId: number) => {
    setApplyingBatchId(batchId);
    try {
      const res = await apiFetch(`${API}/classify-batch/${batchId}/apply`, { method: "POST" });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Falha ao aplicar resultados");
      }
      toast({
        title: "Aplicando resultados",
        description: "Os registros serão classificados em background.",
      });
      // Pequeno polling para refletir o efeito na UI
      [3000, 8000, 20000].forEach((delay) => {
        setTimeout(() => { loadBatches(); loadStats(); loadGrouped(groupPage, filterStatus, filterOffice, filterDateFrom, filterDateTo, filterCategory, filterUf, filterVinculo); }, delay);
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      toast({ title: "Erro", description: msg, variant: "destructive" });
    } finally {
      setApplyingBatchId(null);
    }
  };

  const handleRetryBatchErrors = async (batchId: number) => {
    setRetryingBatchId(batchId);
    try {
      const res = await apiFetch(`${API}/classify-batch/${batchId}/retry-errors`, { method: "POST" });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Falha ao reprocessar erros");
      }
      const result = await res.json();
      toast({
        title: "Reprocessamento iniciado",
        description: `Novo batch #${result.new_batch?.id} criado com ${result.new_batch?.total_records || 0} registros.`,
      });
      loadBatches();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      toast({ title: "Erro", description: msg, variant: "destructive" });
    } finally {
      setRetryingBatchId(null);
    }
  };

  // ─── Rebuild proposals ───────────────────────────────────────────────
  const [rebuildingProposals, setRebuildingProposals] = useState(false);

  const handleRebuildProposals = async () => {
    setRebuildingProposals(true);
    try {
      const params = new URLSearchParams();
      if (filterOffice) params.set("linked_office_id", filterOffice);
      const qs = params.toString() ? `?${params.toString()}` : "";
      const res = await apiFetch(`${API}/rebuild-proposals${qs}`, { method: "POST" });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Falha ao reconstruir propostas");
      }
      const scopeLabel = filterOffice
        ? `escritório ${offices.find((o) => String(o.external_id) === filterOffice)?.name || filterOffice}`
        : "todos os escritórios";
      toast({
        title: "Reconstrução iniciada",
        description: `Propostas sendo reconstruídas para ${scopeLabel}. Atualize em instantes.`,
      });
      setTimeout(() => {
        loadGrouped(groupPage, filterStatus, filterOffice, filterDateFrom, filterDateTo, filterCategory, filterUf, filterVinculo);
      }, 3000);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      toast({ title: "Erro", description: msg, variant: "destructive" });
    } finally {
      setRebuildingProposals(false);
    }
  };

  // ─── Scheduling ──────────────────────────────────────────────────────

  const openScheduleDialog = (group: GroupedRecord) => {
    setScheduleGroup(group);
    const tasks = group.proposed_tasks?.length > 0 ? group.proposed_tasks : (group.proposed_task ? [group.proposed_task] : []);
    setEditedPayloads(tasks.map((t) => ({ ...t })));
    setScheduleOpen(true);
  };

  const handleConfirmSchedule = async () => {
    if (!scheduleGroup) return;
    setScheduling(true);
    const isNoProcess = !scheduleGroup.lawsuit_id;
    try {
      const activeTasks = editedPayloads.filter((_, i) => !removedTaskIndices.has(i));
      const results: string[] = [];

      if (isNoProcess) {
        // Publicações sem processo: agendamento único com N payloads
        const recordIds = scheduleGroup.records.map((r) => r.id);
        const body: any = { record_ids: recordIds, payload_overrides: activeTasks };
        const res = await apiFetch(`${API}/groups/records/schedule`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          throw new Error(data.detail || "Erro ao agendar tarefa.");
        }
        const result = await res.json();
        const ids = result.created_task_ids ?? [result.created_task_id ?? result.task_id ?? "?"];
        results.push(...ids.map(String));
      } else {
        // Publicações com processo vinculado: agendamento único com N payloads
        const body: any = { payload_overrides: activeTasks };
        const res = await apiFetch(`${API}/groups/${scheduleGroup.lawsuit_id}/schedule`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          throw new Error(data.detail || "Erro ao agendar tarefa.");
        }
        const result = await res.json();
        const ids = result.created_task_ids ?? [result.task_id ?? result.created_task_id ?? "?"];
        results.push(...ids.map(String));
      }

      toast({
        title: `${results.length} tarefa(s) agendada(s)!`,
        description: `IDs: ${results.join(", ")}`,
      });
      setScheduleOpen(false);
      setRemovedTaskIndices(new Set());
      loadGrouped(groupPage, filterStatus, filterOffice, filterDateFrom, filterDateTo, filterCategory, filterUf, filterVinculo);
      loadStats();
    } catch (err: any) {
      toast({ title: "Erro ao agendar", description: err.message, variant: "destructive" });
    } finally {
      setScheduling(false);
    }
  };

  // ─── Bulk actions (seleção múltipla de grupos) ───────────────────────

  // Chave estável do grupo (não depende do índice da iteração)
  const groupKey = (group: GroupedRecord): string =>
    `${group.lawsuit_id ?? "nl"}-${group.records[0]?.id ?? "x"}`;

  const toggleGroupSelection = (key: string) => {
    setSelectedGroupKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };

  const toggleSelectAllVisible = () => {
    if (!grouped) return;
    const visibleKeys = grouped.groups.map(groupKey);
    setSelectedGroupKeys((prev) => {
      const allSelected = visibleKeys.every((k) => prev.has(k));
      if (allSelected) {
        const next = new Set(prev);
        visibleKeys.forEach((k) => next.delete(k));
        return next;
      }
      return new Set([...prev, ...visibleKeys]);
    });
  };

  const clearSelection = () => setSelectedGroupKeys(new Set());

  const handleBulkConfirm = async () => {
    if (!grouped) return;
    const selected = grouped.groups.filter((g) => selectedGroupKeys.has(groupKey(g)));
    const schedulable = selected.filter((g) => {
      const tasks = g.proposed_tasks || (g.proposed_task ? [g.proposed_task] : []);
      const status = groupStatusSummary(g);
      return tasks.length > 0 && status !== "AGENDADO";
    });

    if (schedulable.length === 0) {
      toast({
        title: "Nada a confirmar",
        description: "Nenhum grupo selecionado possui proposta pendente.",
        variant: "destructive",
      });
      return;
    }

    setBulkProcessing(true);
    let ok = 0;
    const errors: string[] = [];

    for (const group of schedulable) {
      const tasks = group.proposed_tasks && group.proposed_tasks.length > 0
        ? group.proposed_tasks
        : (group.proposed_task ? [group.proposed_task] : []);
      const payloadOverrides = tasks.map((t) => ({ ...t }));

      try {
        if (!group.lawsuit_id) {
          const recordIds = group.records.map((r) => r.id);
          const res = await apiFetch(`${API}/groups/records/schedule`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ record_ids: recordIds, payload_overrides: payloadOverrides }),
          });
          if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            throw new Error(data.detail || "Erro ao agendar.");
          }
        } else {
          const res = await apiFetch(`${API}/groups/${group.lawsuit_id}/schedule`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ payload_overrides: payloadOverrides }),
          });
          if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            throw new Error(data.detail || "Erro ao agendar.");
          }
        }
        ok += 1;
      } catch (err: any) {
        errors.push(`${group.lawsuit_cnj ?? group.lawsuit_id ?? "sem processo"}: ${err.message}`);
      }
    }

    toast({
      title: `${ok} grupo(s) agendado(s)`,
      description: errors.length > 0 ? `Falhas: ${errors.slice(0, 3).join(" | ")}${errors.length > 3 ? ` (+${errors.length - 3})` : ""}` : undefined,
      variant: errors.length > 0 ? "destructive" : "default",
    });

    clearSelection();
    setBulkProcessing(false);
    loadGrouped(groupPage, filterStatus, filterOffice, filterDateFrom, filterDateTo, filterCategory, filterUf, filterVinculo);
    loadStats();
  };

  const handleBulkIgnore = async () => {
    if (!grouped) return;
    const selected = grouped.groups.filter((g) => selectedGroupKeys.has(groupKey(g)));
    const recordIds = selected.flatMap((g) =>
      g.records.filter((r) => r.status !== "AGENDADO" && r.status !== "IGNORADO").map((r) => r.id),
    );

    if (recordIds.length === 0) {
      toast({
        title: "Nada a ignorar",
        description: "As publicações selecionadas já estão agendadas ou ignoradas.",
        variant: "destructive",
      });
      return;
    }

    setBulkProcessing(true);
    const results = await Promise.allSettled(
      recordIds.map((id) =>
        apiFetch(`${API}/records/${id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status: "IGNORADO" }),
        }),
      ),
    );
    const ok = results.filter((r) => r.status === "fulfilled").length;
    const failed = results.length - ok;

    toast({
      title: `${ok} publicação(ões) ignorada(s)`,
      description: failed > 0 ? `${failed} falharam.` : undefined,
      variant: failed > 0 ? "destructive" : "default",
    });

    clearSelection();
    setBulkProcessing(false);
    loadGrouped(groupPage, filterStatus, filterOffice, filterDateFrom, filterDateTo, filterCategory, filterUf, filterVinculo);
    loadStats();
  };

  // ─── Derived ─────────────────────────────────────────────────────────

  const totalPages = grouped ? Math.ceil(grouped.total_groups / GROUP_PAGE_SIZE) : 0;

  // UFs disponíveis na página atual (derivadas do CNJ). A lista é limitada ao
  // que vem do servidor na página vigente; inclui sempre a UF atualmente
  // selecionada pra evitar sumir do Select quando o resultado fica vazio.
  const availableUfs: string[] = grouped
    ? (() => {
        const ufs = new Set(
          grouped.groups
            .map((g) => ufFromCnj(g.lawsuit_cnj))
            .filter((u): u is string => !!u),
        );
        if (filterUf) ufs.add(filterUf);
        return Array.from(ufs).sort();
      })()
    : (filterUf ? [filterUf] : []);

  // O filtro UF agora é server-side, então os grupos já vêm filtrados.
  const visibleGroups: GroupedRecord[] = grouped ? grouped.groups : [];

  const groupStatusSummary = (group: GroupedRecord) => {
    const statuses = group.records.map((r) => r.status);
    if (statuses.every((s) => s === "AGENDADO")) return "AGENDADO";
    if (statuses.some((s) => s === "CLASSIFICADO")) return "CLASSIFICADO";
    if (statuses.some((s) => s === "ERRO")) return "ERRO";
    if (statuses.some((s) => s === "IGNORADO") && statuses.every((s) => s === "IGNORADO" || s === "AGENDADO")) return "IGNORADO";
    return "NOVO";
  };

  const officeName = (id: number | null) => {
    if (!id) return null;
    const o = offices.find((o) => o.external_id === id);
    return o ? (o.path || o.name) : String(id);
  };

  // ─── Render ──────────────────────────────────────────────────────────

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
            <Newspaper className="h-6 w-6" />
            Publicações Legal One
          </h1>
          <p className="text-muted-foreground">
            Busque, classifique e agende tarefas a partir de publicações judiciais.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" asChild>
            <Link to="/publications/templates">
              <Settings className="mr-2 h-4 w-4" />
              Configurar Templates
            </Link>
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={handleRebuildProposals}
            disabled={rebuildingProposals}
            title="Reconstrói propostas de agendamento para registros já classificados (útil após criar novos templates)"
          >
            <RefreshCw className={`mr-2 h-4 w-4 ${rebuildingProposals ? "animate-spin" : ""}`} />
            Reaplicar Templates
          </Button>
          <Button variant="outline" size="sm" onClick={handleRefreshAll}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Atualizar
          </Button>
        </div>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Erro</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* Stats */}
      {stats && (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-5">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Total</CardTitle>
              <BarChart3 className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stats.total_records}</div>
              <p className="text-xs text-muted-foreground">{stats.total_searches} buscas</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Novas</CardTitle>
              <Clock className="h-4 w-4 text-blue-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-blue-600">{stats.by_status.novo}</div>
              <p className="text-xs text-muted-foreground">Aguardando classificação</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Classificadas</CardTitle>
              <CheckCircle2 className="h-4 w-4 text-amber-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-amber-600">{stats.by_status.classificado}</div>
              <p className="text-xs text-muted-foreground">Aguardando confirmação</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Agendadas</CardTitle>
              <Calendar className="h-4 w-4 text-green-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-green-600">{stats.by_status.agendado}</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Erros/Ignoradas</CardTitle>
              <XCircle className="h-4 w-4 text-red-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-red-600">
                {stats.by_status.erro + stats.by_status.ignorado}
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Search Panel */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Search className="h-5 w-5" />
            Disparar Nova Busca
          </CardTitle>
          <CardDescription>
            Busca publicações, enriquece com escritório responsável, classifica automaticamente e monta proposta de tarefa.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap items-end gap-4">
            <div className="grid gap-1.5">
              <Label htmlFor="dateFrom">Data Inicial *</Label>
              <Input id="dateFrom" type="date" value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)} className="w-[160px]" />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="dateTo">Data Final</Label>
              <Input id="dateTo" type="date" value={dateTo}
                onChange={(e) => setDateTo(e.target.value)} className="w-[160px]" />
            </div>
            <div className="grid gap-1.5">
              <Label>Origem</Label>
              <Select value={originType} onValueChange={setOriginType}>
                <SelectTrigger className="w-[200px]"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="OfficialJournalsCrawler">Diário Oficial</SelectItem>
                  <SelectItem value="ProgressesCrawler">Andamentos (Crawler)</SelectItem>
                  <SelectItem value="Manual">Manual</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-1.5">
              <Label>Escritório Responsável</Label>
              <Select value={searchOfficeId || "_all"}
                onValueChange={(v) => setSearchOfficeId(v === "_all" ? "" : v)}>
                <SelectTrigger className="w-[220px]">
                  <SelectValue placeholder="Todos os escritórios" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="_all">Todos os escritórios</SelectItem>
                  {offices.map((o) => (
                    <SelectItem key={o.external_id} value={String(o.external_id)}>{officeLabel(o)}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex items-center gap-2 self-end">
              <Checkbox
                id="searchOnlyUnlinked"
                checked={searchOnlyUnlinked}
                onCheckedChange={(v) => setSearchOnlyUnlinked(!!v)}
              />
              <Label htmlFor="searchOnlyUnlinked" className="text-xs cursor-pointer whitespace-nowrap">
                Apenas sem processo
              </Label>
            </div>
            <Button onClick={handleSearch} disabled={isSearching || !dateFrom} className="self-end">
              {isSearching ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Search className="mr-2 h-4 w-4" />}
              Buscar
            </Button>
          </div>
          {searchOfficeId && indexStatus && (
            <div className="mt-3 rounded-md border bg-muted/30 p-3 text-xs flex flex-wrap items-center gap-3">
              <span className="font-medium">Índice de processos:</span>
              <span>{indexStatus.total_ids.toLocaleString()} processos</span>
              {indexStatus.is_fresh ? (
                <span className="rounded bg-green-100 text-green-800 px-2 py-0.5">atualizado</span>
              ) : (
                <span className="rounded bg-amber-100 text-amber-800 px-2 py-0.5">desatualizado</span>
              )}
              {indexStatus.last_full_sync_at && (
                <span className="text-muted-foreground">
                  último full: {new Date(indexStatus.last_full_sync_at).toLocaleString("pt-BR")}
                </span>
              )}
              {indexStatus.in_progress ? (
                <span className="flex items-center gap-2">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  sincronizando... {indexStatus.progress_pct}%
                </span>
              ) : (
                <>
                  <Button size="sm" variant="outline" className="h-6 text-xs"
                    onClick={() => handleSyncIndex(false)}>
                    Atualizar
                  </Button>
                  <Button size="sm" variant="ghost" className="h-6 text-xs"
                    onClick={() => handleSyncIndex(true)}>
                    Full sync
                  </Button>
                </>
              )}
              {indexStatus.last_sync_status === "error" && (
                <span className="text-red-600">erro no último sync</span>
              )}
            </div>
          )}
          {activeSearch && (
            <div className="mt-3 rounded-md border border-blue-200 bg-blue-50 p-3 space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Loader2 className="h-4 w-4 animate-spin text-blue-600" />
                  <span className="text-sm font-medium text-blue-800">
                    Busca #{activeSearch.id} em andamento
                  </span>
                </div>
                <span className="text-xs font-semibold text-blue-700">
                  {activeSearch.progress_pct ?? 0}%
                </span>
              </div>
              <Progress value={activeSearch.progress_pct ?? 0} className="h-2" />
              <p className="text-xs text-blue-700">
                {activeSearch.progress_detail || "Iniciando..."}
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Search History (collapsible) */}
      {searches.length > 0 && (
        <Card>
          <CardHeader className="cursor-pointer select-none py-3"
            onClick={() => setSearchesExpanded(!searchesExpanded)}>
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium">
                Histórico de Buscas
                <Badge variant="secondary" className="ml-2">{searches.length}</Badge>
              </CardTitle>
              {searchesExpanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            </div>
          </CardHeader>
          {searchesExpanded && (
            <CardContent className="pt-0">
              <ScrollArea className="max-h-[200px]">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>ID</TableHead>
                      <TableHead>Período</TableHead>
                      <TableHead>Escritório</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Encontradas</TableHead>
                      <TableHead>Novas</TableHead>
                      <TableHead>Data</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {searches.map((s) => (
                      <TableRow key={s.id}>
                        <TableCell className="font-mono text-xs">#{s.id}</TableCell>
                        <TableCell className="text-xs">
                          {formatDateShort(s.date_from)}{s.date_to ? ` → ${formatDateShort(s.date_to)}` : ""}
                        </TableCell>
                        <TableCell className="text-xs">
                          {s.office_filter ? (officeName(parseInt(s.office_filter)) || s.office_filter) : "—"}
                        </TableCell>
                        <TableCell>
                          <Badge variant={statusColor(s.status)} className="text-xs">{s.status}</Badge>
                        </TableCell>
                        <TableCell className="font-semibold">{s.total_found}</TableCell>
                        <TableCell className="text-green-600">{s.total_new}</TableCell>
                        <TableCell className="text-xs">{formatDate(s.created_at)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </ScrollArea>
            </CardContent>
          )}
        </Card>
      )}

      {/* Batch classification (Anthropic Message Batches API) */}
      <Card>
        <CardHeader className="cursor-pointer select-none py-3"
          onClick={() => setBatchesExpanded(!batchesExpanded)}>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2 text-sm font-medium">
              <Layers className="h-4 w-4" />
              Classificação em Lote (Batch API)
              {batches.length > 0 && <Badge variant="secondary">{batches.length}</Badge>}
            </CardTitle>
            {batchesExpanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          </div>
          <CardDescription>
            Envia milhares de publicações em um único lote à Anthropic (50% mais barato, até 24h). Use para volumes grandes.
          </CardDescription>
        </CardHeader>
        {batchesExpanded && (
          <CardContent className="space-y-4">
            {/* Form para submeter um novo batch */}
            <div className="flex flex-wrap items-end gap-3 rounded border bg-muted/30 p-3">
              <div className="grid gap-1.5">
                <Label className="text-xs">Escritório (opcional)</Label>
                <Select value={batchOfficeId || "_all"}
                  onValueChange={(v) => setBatchOfficeId(v === "_all" ? "" : v)}>
                  <SelectTrigger className="w-[220px]">
                    <SelectValue placeholder="Todos" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="_all">Todos os escritórios</SelectItem>
                    {offices.map((o) => (
                      <SelectItem key={o.external_id} value={String(o.external_id)}>
                        {officeLabel(o)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="grid gap-1.5">
                <Label className="text-xs">Limite (opcional)</Label>
                <Input type="number" placeholder="Ex.: 3000"
                  value={batchLimit} onChange={(e) => setBatchLimit(e.target.value)}
                  className="w-[140px]" />
              </div>
              <div className="flex items-center gap-2 self-end">
                <Checkbox
                  id="batchOnlyUnlinked"
                  checked={batchOnlyUnlinked}
                  onCheckedChange={(v) => setBatchOnlyUnlinked(!!v)}
                />
                <Label htmlFor="batchOnlyUnlinked" className="text-xs cursor-pointer whitespace-nowrap">
                  Apenas sem processo
                </Label>
              </div>
              <Button onClick={handleSubmitBatch} disabled={submittingBatch}>
                {submittingBatch
                  ? <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  : <Play className="mr-2 h-4 w-4" />}
                Enviar lote
              </Button>
              <Button variant="outline" onClick={loadBatches} size="sm">
                <RefreshCw className="mr-2 h-3.5 w-3.5" />
                Atualizar lista
              </Button>
              <span className="ml-auto text-xs text-muted-foreground">
                Deduplicação: uma publicação por processo/dia é enviada ao agente. As demais herdam a classificação.
              </span>
            </div>

            {/* Lista de batches */}
            {batches.length === 0 ? (
              <div className="flex h-20 items-center justify-center text-xs text-muted-foreground">
                Nenhum lote enviado ainda.
              </div>
            ) : (
              <ScrollArea className="max-h-[260px] rounded border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-[70px]">ID</TableHead>
                      <TableHead className="w-[120px]">Status</TableHead>
                      <TableHead className="w-[80px] text-right">Total</TableHead>
                      <TableHead className="w-[90px] text-right">Sucesso</TableHead>
                      <TableHead className="w-[80px] text-right">Erros</TableHead>
                      <TableHead className="w-[180px]">Criado</TableHead>
                      <TableHead className="w-[180px]">Ações</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {batches.map((b) => (
                      <TableRow key={b.id}>
                        <TableCell className="font-mono text-xs">#{b.id}</TableCell>
                        <TableCell>
                          <Badge variant={batchStatusColor(b.status)} className="text-xs">
                            {batchStatusLabel(b.status)}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-right text-xs">{b.total_records}</TableCell>
                        <TableCell className="text-right text-xs text-green-700">
                          {b.succeeded_count}
                        </TableCell>
                        <TableCell className="text-right text-xs text-red-600">
                          {b.errored_count + b.expired_count + b.canceled_count}
                        </TableCell>
                        <TableCell className="text-xs">{formatDate(b.created_at)}</TableCell>
                        <TableCell>
                          <div className="flex gap-1">
                            {b.status !== "APLICADO" && b.status !== "FALHA" && (
                              <Button size="sm" variant="outline"
                                className="h-7 px-2 text-xs"
                                disabled={refreshingBatchId === b.id}
                                onClick={() => handleRefreshBatch(b.id)}
                                title="Consultar status na Anthropic">
                                {refreshingBatchId === b.id
                                  ? <Loader2 className="h-3 w-3 animate-spin" />
                                  : <RefreshCw className="h-3 w-3" />}
                              </Button>
                            )}
                            {b.status === "PRONTO" && (
                              <Button size="sm"
                                className="h-7 px-2 text-xs"
                                disabled={applyingBatchId === b.id}
                                onClick={() => handleApplyBatch(b.id)}
                                title="Baixar e aplicar classificações">
                                {applyingBatchId === b.id
                                  ? <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                                  : <Send className="mr-1 h-3 w-3" />}
                                Aplicar
                              </Button>
                            )}
                          </div>
                          {/* Retry errors button */}
                          {b.status === "APLICADO" && (b.errored_count > 0 || b.expired_count > 0) && (
                            <div className="mt-1 flex gap-1">
                              <Button size="sm" variant="outline"
                                className="h-6 px-2 text-[10px] text-orange-700 border-orange-300"
                                disabled={retryingBatchId === b.id}
                                onClick={() => handleRetryBatchErrors(b.id)}
                                title="Reprocessar itens que falharam">
                                {retryingBatchId === b.id
                                  ? <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                                  : <RotateCcw className="mr-1 h-3 w-3" />}
                                Retry {b.errored_count + b.expired_count} erros
                              </Button>
                              {b.error_details && (
                                <Button size="sm" variant="ghost"
                                  className="h-6 px-2 text-[10px]"
                                  onClick={() => setErrorDetailsBatchId(
                                    errorDetailsBatchId === b.id ? null : b.id
                                  )}
                                  title="Ver detalhes dos erros">
                                  <Eye className="h-3 w-3" />
                                </Button>
                              )}
                            </div>
                          )}
                          {b.error_message && (
                            <div className="mt-0.5 max-w-[240px] truncate text-[10px] text-red-600"
                              title={b.error_message}>
                              {b.error_message}
                            </div>
                          )}
                          {/* Error details expansion */}
                          {errorDetailsBatchId === b.id && b.error_details && (
                            <div className="mt-1 max-h-[120px] overflow-y-auto rounded border border-red-200 bg-red-50 p-1.5 text-[10px]">
                              {Object.entries(b.error_details).map(([recId, reason]) => (
                                <div key={recId} className="flex gap-1 py-0.5">
                                  <span className="font-mono font-semibold text-red-700">#{recId}:</span>
                                  <span className="text-red-600">{reason}</span>
                                </div>
                              ))}
                            </div>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </ScrollArea>
            )}
          </CardContent>
        )}
      </Card>

      {/* Groups */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between mb-4">
            <CardTitle className="flex items-center gap-2">
              <BookOpen className="h-5 w-5" />
              Processos com Publicações
              {grouped && (
                <>
                  <Badge variant="secondary">{grouped.total_groups} grupos</Badge>
                  {typeof grouped.total_records === "number" && (
                    <Badge variant="outline">{grouped.total_records} publicações</Badge>
                  )}
                  {filterUf && <Badge variant="default">UF: {filterUf}</Badge>}
                </>
              )}
            </CardTitle>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => setIsSaveFilterDialogOpen(true)}
              >
                <Save className="h-4 w-4 mr-2" />
                Salvar Filtros
              </Button>
              {savedFilters.length > 0 && (
                <Select onValueChange={(v) => {
                  const filter = savedFilters.find(f => f.id === parseInt(v));
                  if (filter) handleApplySavedFilter(filter);
                }}>
                  <SelectTrigger className="w-[180px]">
                    <SelectValue placeholder="Filtros salvos" />
                  </SelectTrigger>
                  <SelectContent>
                    {savedFilters.map(f => (
                      <SelectItem key={f.id} value={String(f.id)}>
                        {f.name} {f.is_default ? "(padrão)" : ""}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
              <Filter className="h-4 w-4 text-muted-foreground" />
              <Select value={filterStatus || "all"}
                onValueChange={(v) => handleFilterChange(v === "all" ? "" : v, filterOffice)}>
                <SelectTrigger className="w-[140px]"><SelectValue placeholder="Status" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Todos</SelectItem>
                  <SelectItem value="NOVO">Novos</SelectItem>
                  <SelectItem value="CLASSIFICADO">Classificados</SelectItem>
                  <SelectItem value="AGENDADO">Agendados</SelectItem>
                  <SelectItem value="IGNORADO">Ignorados</SelectItem>
                  <SelectItem value="ERRO">Com erro</SelectItem>
                  <SelectItem value="DESCARTADO_OBSOLETA">Obsoletas</SelectItem>
                </SelectContent>
              </Select>
              <Select value={filterOffice || "all"}
                onValueChange={(v) => handleFilterChange(filterStatus, v === "all" ? "" : v)}>
                <SelectTrigger className="w-[200px]">
                  <SelectValue placeholder="Todos os escritórios" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Todos os escritórios</SelectItem>
                  {offices.map((o) => (
                    <SelectItem key={o.external_id} value={String(o.external_id)}>{officeLabel(o)}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select value={filterCategory || "all"}
                onValueChange={(v) => handleFilterChange(filterStatus, filterOffice, undefined, undefined, v === "all" ? "" : v)}>
                <SelectTrigger className="w-[180px]">
                  <SelectValue placeholder="Classificação" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Todas as classificações</SelectItem>
                  {Object.entries(taxonomy).map(([cat]) => (
                    <SelectItem key={cat} value={cat}>{cat}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select value={filterUf || "all"}
                onValueChange={(v) => handleFilterChange(filterStatus, filterOffice, undefined, undefined, undefined, v === "all" ? "" : v)}>
                <SelectTrigger className="w-[120px]">
                  <SelectValue placeholder="UF" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Todas UFs</SelectItem>
                  {availableUfs.map((uf) => (
                    <SelectItem key={uf} value={uf}>{uf}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select value={filterVinculo || "all"}
                onValueChange={(v) => handleFilterChange(filterStatus, filterOffice, undefined, undefined, undefined, undefined, v === "all" ? "" : v)}>
                <SelectTrigger className="w-[160px]">
                  <SelectValue placeholder="Vínculo" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Todos os vínculos</SelectItem>
                  <SelectItem value="com_processo">Com processo</SelectItem>
                  <SelectItem value="sem_processo">Sem processo</SelectItem>
                </SelectContent>
              </Select>
              <div className="flex items-center gap-1">
                <div className="relative flex items-center gap-1">
                  <Input
                    type="date"
                    value={filterDateFrom}
                    onChange={(e) => handleFilterChange(filterStatus, filterOffice, e.target.value, undefined)}
                    onClick={(e) => (e.currentTarget as HTMLInputElement).showPicker?.()}
                    onFocus={(e) => (e.currentTarget as HTMLInputElement).showPicker?.()}
                    className="h-8 w-[130px] text-xs pl-8 cursor-pointer"
                    title="Data captura (Ajus) — início"
                  />
                  <Calendar className="absolute left-2 h-3.5 w-3.5 text-muted-foreground pointer-events-none" />
                </div>
                <span className="text-xs text-muted-foreground">a</span>
                <div className="relative flex items-center gap-1">
                  <Input
                    type="date"
                    value={filterDateTo}
                    onChange={(e) => handleFilterChange(filterStatus, filterOffice, undefined, e.target.value)}
                    onClick={(e) => (e.currentTarget as HTMLInputElement).showPicker?.()}
                    onFocus={(e) => (e.currentTarget as HTMLInputElement).showPicker?.()}
                    className="h-8 w-[130px] text-xs pl-8 cursor-pointer"
                    title="Data captura (Ajus) — fim"
                  />
                  <Calendar className="absolute left-2 h-3.5 w-3.5 text-muted-foreground pointer-events-none" />
                </div>
                {(filterDateFrom || filterDateTo) && (
                  <button
                    type="button"
                    onClick={() => handleFilterChange(filterStatus, filterOffice, "", "")}
                    className="rounded p-0.5 text-muted-foreground hover:text-destructive transition-colors"
                    title="Limpar filtro de data"
                  >
                    <XCircle className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
              <div className="ml-auto">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={handleExportExcel}
                  disabled={isExporting}
                  title="Exporta as publicações conforme os filtros atuais para um arquivo Excel"
                >
                  {isExporting ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <FileDown className="h-4 w-4" />
                  )}
                  <span className="ml-2">Exportar Excel</span>
                </Button>
              </div>
          </div>
        </CardHeader>
        <CardContent>
          {!grouped || visibleGroups.length === 0 ? (
            <div className="flex h-32 items-center justify-center text-muted-foreground">
              {grouped && filterUf
                ? `Nenhum grupo encontrado para a UF ${filterUf} com os filtros atuais.`
                : "Nenhum registro encontrado. Dispare uma busca acima."}
            </div>
          ) : (
            <>
              {selectedGroupKeys.size > 0 && (
                <div className="mb-2 flex items-center justify-between gap-2 rounded border border-primary/30 bg-primary/5 px-3 py-2 text-sm">
                  <span>
                    <strong>{selectedGroupKeys.size}</strong> grupo(s) selecionado(s)
                  </span>
                  <div className="flex gap-2">
                    <Button size="sm" variant="default" disabled={bulkProcessing} onClick={handleBulkConfirm}>
                      <Send className="mr-1 h-3 w-3" />
                      Confirmar agendamentos
                    </Button>
                    <Button size="sm" variant="outline" disabled={bulkProcessing} onClick={handleBulkIgnore}>
                      <EyeOff className="mr-1 h-3 w-3" />
                      Ignorar selecionados
                    </Button>
                    <Button size="sm" variant="ghost" disabled={bulkProcessing} onClick={clearSelection}>
                      Limpar seleção
                    </Button>
                  </div>
                </div>
              )}
              <ScrollArea className="h-[min(820px,calc(100vh-280px))] rounded border text-[13px]">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-[40px]">
                        <Checkbox
                          checked={
                            visibleGroups.length > 0 &&
                            visibleGroups.every((g) => selectedGroupKeys.has(groupKey(g)))
                          }
                          onCheckedChange={toggleSelectAllVisible}
                          aria-label="Selecionar todos os grupos visíveis"
                        />
                      </TableHead>
                      <TableHead className="w-[130px]">Processo</TableHead>
                      <TableHead className="w-[160px]">Escritório</TableHead>
                      <TableHead className="w-[100px]">Datas</TableHead>
                      <TableHead>Publicações</TableHead>
                      <TableHead className="w-[120px]">Classificação</TableHead>
                      <TableHead className="w-[90px]">Status</TableHead>
                      <TableHead className="w-[190px]">Proposta de Tarefa</TableHead>
                      <TableHead className="w-[110px]">Ações</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {visibleGroups.map((group, gi) => {
                      const status = groupStatusSummary(group);
                      // Classificações: usa array do grupo ou fallback dos records
                      const groupClassifications = group.classifications && group.classifications.length > 0
                        ? group.classifications
                        : [];
                      const categories = groupClassifications.length > 0
                        ? [...new Set(groupClassifications.map((c) => c.categoria))]
                        : [...new Set(group.records.map((r) => r.category).filter(Boolean))];
                      const subcategories = groupClassifications.length > 0
                        ? [...new Set(groupClassifications.map((c) => c.subcategoria).filter((s) => s && s !== "-"))]
                        : [...new Set(group.records.map((r) => r.subcategory).filter((s) => s && s !== "-"))];
                      const polos = groupClassifications.length > 0
                        ? [...new Set(groupClassifications.map((c) => c.polo).filter(Boolean))] as string[]
                        : [...new Set(group.records.map((r) => r.polo).filter(Boolean))] as string[];
                      // Pega a data/hora de audiência do primeiro record que tem
                      const audRecord = group.records.find((r) => r.audiencia_data);
                      const proposedTasks = group.proposed_tasks || (group.proposed_task ? [group.proposed_task] : []);
                      const hasProposal = proposedTasks.length > 0;

                      const gKey = groupKey(group);
                      return (
                        <TableRow key={`${group.lawsuit_id}-${gi}`}>
                          <TableCell className="w-[40px]">
                            <Checkbox
                              checked={selectedGroupKeys.has(gKey)}
                              onCheckedChange={() => toggleGroupSelection(gKey)}
                              aria-label="Selecionar grupo"
                            />
                          </TableCell>
                          <TableCell className="font-mono text-xs">
                            {group.lawsuit_cnj ? (
                              <div title={group.lawsuit_cnj}>
                                <div className="flex items-center gap-1">
                                  <div className="max-w-[110px] truncate font-medium">{group.lawsuit_cnj}</div>
                                  {(() => {
                                    const uf = ufFromCnj(group.lawsuit_cnj);
                                    if (!uf) return null;
                                    return (
                                      <span className="inline-flex shrink-0 rounded border border-slate-300 bg-slate-100 px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-slate-700"
                                        title="UF derivada do CNJ">
                                        {uf}
                                      </span>
                                    );
                                  })()}
                                </div>
                                <div className="text-muted-foreground">ID: {group.lawsuit_id}</div>
                              </div>
                            ) : group.lawsuit_id ? (
                              <span className="text-muted-foreground">{group.lawsuit_id}</span>
                            ) : (
                              <div>
                                <span className="italic text-orange-600">sem processo</span>
                                {(() => {
                                  const naturezas = [...new Set(
                                    group.records
                                      .map((r) => r.natureza_processo)
                                      .filter(Boolean)
                                  )];
                                  return naturezas.length > 0 ? (
                                    <div className="flex flex-wrap gap-1 mt-0.5">
                                      {naturezas.map((n: string) => (
                                        <Badge key={n} variant="outline" className="text-[9px] px-1 py-0 border-orange-300 text-orange-700 font-normal">
                                          {n}
                                        </Badge>
                                      ))}
                                    </div>
                                  ) : null;
                                })()}
                                <div className="text-[10px] text-muted-foreground">
                                  {group.records.length} publicação(ões)
                                </div>
                              </div>
                            )}
                          </TableCell>
                          <TableCell className="text-xs">
                            {group.office_id ? (
                              <div className="flex items-center gap-1">
                                <Building2 className="h-3 w-3 flex-shrink-0 text-muted-foreground" />
                                <span className="truncate">{officeName(group.office_id) || group.office_id}</span>
                              </div>
                            ) : <span className="text-muted-foreground">—</span>}
                          </TableCell>
                          <TableCell className="text-xs">
                            {(() => {
                              const first = group.records[0];
                              return (
                                <div className="space-y-1">
                                  <div title="Data da publicação (tribunal) — para contagem de prazo">
                                    <div className="text-[10px] text-muted-foreground">Publicação</div>
                                    <div className="font-medium">{formatDateShort(first.publication_date)}</div>
                                  </div>
                                  <div title="Data de captura (Ajus) — referência do fluxo de trabalho">
                                    <div className="text-[10px] text-muted-foreground">Captura</div>
                                    <div>{formatDateShort(first.creation_date)}</div>
                                  </div>
                                </div>
                              );
                            })()}
                          </TableCell>
                          <TableCell>
                            <div className="space-y-0.5">
                              {group.records.slice(0, 2).map((r) => (
                                <div key={r.id} className="flex items-center gap-1">
                                  <span className="max-w-[200px] truncate text-xs text-muted-foreground">
                                    {r.description_preview || String(r.legal_one_update_id)}
                                  </span>
                                  <Button variant="ghost" size="sm" className="h-5 w-5 flex-shrink-0 p-0"
                                    onClick={() => loadRecordDetail(r.id)}
                                    title="Ver detalhes">
                                    <Eye className="h-3 w-3" />
                                  </Button>
                                </div>
                              ))}
                              {group.records.length > 2 && (
                                <div className="text-xs text-muted-foreground">
                                  + {group.records.length - 2} mais
                                </div>
                              )}
                            </div>
                          </TableCell>
                          <TableCell className="text-xs">
                            {(() => {
                              const groupKey = `${group.lawsuit_id ?? "null"}-${gi}`;
                              const recordIds = group.records.map((r) => r.id);
                              const primaryCat = categories[0] || "";
                              const primarySub = subcategories[0] || "";
                              const currentValue = primaryCat
                                ? primarySub
                                  ? `${primaryCat}|||${primarySub}`
                                  : primaryCat
                                : "";
                              const isReclassifying = reclassifyingGroup === groupKey;
                              return (
                                <div className="space-y-1">
                                  {categories.length > 0 && (
                                    <div className="space-y-0.5">
                                      {categories.map((cat, ci) => (
                                        <div key={ci}>
                                          <div className="font-medium">{cat}</div>
                                          {subcategories[ci] && (
                                            <div className="text-muted-foreground">{subcategories[ci]}</div>
                                          )}
                                        </div>
                                      ))}
                                      {categories.length > 1 && (
                                        <div className="text-[10px] text-muted-foreground italic">
                                          {categories.length} classificações
                                        </div>
                                      )}
                                    </div>
                                  )}

                                  {/* Dropdown de reclassificação manual */}
                                  <Select
                                    value={currentValue}
                                    disabled={isReclassifying}
                                    onValueChange={(v) => {
                                      if (v === currentValue) return;
                                      handleReclassifyGroup(groupKey, recordIds, v);
                                    }}
                                  >
                                    <SelectTrigger className="h-6 border-dashed px-1 py-0 text-[10px]">
                                      <SelectValue placeholder={
                                        isReclassifying
                                          ? "Aplicando..."
                                          : categories.length === 0
                                            ? "Classificar manualmente"
                                            : "Alterar classificação"
                                      } />
                                    </SelectTrigger>
                                    <SelectContent className="max-h-80">
                                      {Object.entries(taxonomy).map(([cat, subs]) => (
                                        <div key={cat}>
                                          {subs && subs.length > 0 ? (
                                            <>
                                              <div className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                                                {cat}
                                              </div>
                                              {subs.map((sub) => (
                                                <SelectItem
                                                  key={`${cat}|||${sub}`}
                                                  value={`${cat}|||${sub}`}
                                                >
                                                  {sub}
                                                </SelectItem>
                                              ))}
                                            </>
                                          ) : (
                                            <SelectItem value={cat}>{cat}</SelectItem>
                                          )}
                                        </div>
                                      ))}
                                    </SelectContent>
                                  </Select>
                                  {categories.length > 0 && (
                                    <Button
                                      variant="ghost"
                                      size="sm"
                                      className="h-5 w-5 p-0 text-muted-foreground hover:text-red-600"
                                      title="Reportar classificação errada"
                                      onClick={() => openFeedback(group.records[0])}
                                    >
                                      <ThumbsDown className="h-3 w-3" />
                                    </Button>
                                  )}
                                {polos.length > 0 && (
                                  <div className="flex flex-wrap gap-1 pt-0.5">
                                    {polos.map((p) => {
                                      const info = poloLabel(p);
                                      return info ? (
                                        <span key={p}
                                          className={`inline-flex rounded border px-1 py-0 text-[10px] font-medium ${info.className}`}>
                                          {info.label}
                                        </span>
                                      ) : null;
                                    })}
                                  </div>
                                )}
                                {audRecord && (
                                  <div className="mt-0.5 space-y-0.5">
                                    <div className="flex items-center gap-1 text-[10px] font-semibold text-violet-700"
                                      title="Data/hora da audiência extraída pelo classificador">
                                      <Calendar className="h-3 w-3" />
                                      {audRecord.audiencia_data
                                        ? new Date(audRecord.audiencia_data + "T12:00:00").toLocaleDateString("pt-BR")
                                        : "—"
                                      }
                                      {audRecord.audiencia_hora && (
                                        <span className="ml-0.5">{audRecord.audiencia_hora}</span>
                                      )}
                                    </div>
                                    {audRecord.audiencia_link && (
                                      <a href={audRecord.audiencia_link} target="_blank" rel="noopener noreferrer"
                                        className="flex items-center gap-0.5 text-[10px] font-medium text-blue-600 hover:underline"
                                        title={audRecord.audiencia_link}>
                                        <Link2 className="h-3 w-3" />
                                        Link da audiência
                                        <ExternalLink className="h-2.5 w-2.5" />
                                      </a>
                                    )}
                                  </div>
                                )}
                                </div>
                              );
                            })()}
                          </TableCell>
                          <TableCell>
                            <Badge variant={statusColor(status)} className="text-xs">{status}</Badge>
                          </TableCell>
                          <TableCell className="text-xs">
                            {hasProposal ? (
                              <div className="space-y-1">
                                {proposedTasks.slice(0, 3).map((pt, pi) => (
                                  <div key={pi} className={pi > 0 ? "border-t pt-1" : ""}>
                                    <div className="max-w-[180px] truncate font-medium text-green-700"
                                      title={pt.description}>
                                      {pt.description}
                                    </div>
                                    <div className="text-muted-foreground">
                                      Prazo: {formatDateShort(pt.endDateTime ?? null)}
                                    </div>
                                    {pt.suggested_responsible?.name && (
                                      <div className="text-[10px] text-blue-600 truncate max-w-[180px]"
                                        title={`Responsável da pasta: ${pt.suggested_responsible.name}`}>
                                        Resp.: {pt.suggested_responsible.name}
                                      </div>
                                    )}
                                  </div>
                                ))}
                                {proposedTasks.length > 3 && (
                                  <div className="text-[10px] text-muted-foreground italic">
                                    + {proposedTasks.length - 3} tarefas
                                  </div>
                                )}
                              </div>
                            ) : (
                              <span className="italic text-muted-foreground">
                                {status === "AGENDADO" ? "Já agendado" : "Sem template"}
                              </span>
                            )}
                          </TableCell>
                          <TableCell>
                            <div className="flex flex-col gap-1">
                              {status !== "AGENDADO" && (
                                <Button size="sm"
                                  className="h-7 px-2 text-xs"
                                  variant={hasProposal ? "default" : "outline"}
                                  onClick={() => openScheduleDialog(group)}>
                                  <Send className="mr-1 h-3 w-3" />
                                  {hasProposal ? "Confirmar" : "Agendar"}
                                </Button>
                              )}
                              {group.records.some((r) => r.status !== "AGENDADO" && r.status !== "IGNORADO") && (
                                <Button size="sm" variant="ghost"
                                  className="h-7 px-2 text-xs text-muted-foreground"
                                  onClick={() => group.records.filter((r) => r.status !== "AGENDADO" && r.status !== "IGNORADO")
                                    .forEach((r) => handleIgnoreRecord(r.id))}>
                                  Ignorar
                                </Button>
                              )}
                            </div>
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </ScrollArea>

              {totalPages > 1 && (
                <div className="mt-4 flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">
                    Página {groupPage + 1} de {totalPages}
                  </span>
                  <div className="flex gap-2">
                    <Button variant="outline" size="sm" disabled={groupPage === 0}
                      onClick={() => handleGroupPageChange(groupPage - 1)}>
                      <ChevronLeft className="h-4 w-4" />
                    </Button>
                    <Button variant="outline" size="sm" disabled={groupPage >= totalPages - 1}
                      onClick={() => handleGroupPageChange(groupPage + 1)}>
                      <ChevronRight className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      {/* Detail Dialog */}
      <Dialog open={detailOpen} onOpenChange={setDetailOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>
              Publicação #{selectedRecord?.id} (LO: {selectedRecord?.legal_one_update_id})
            </DialogTitle>
            <DialogDescription>Detalhe completo do registro.</DialogDescription>
          </DialogHeader>
          {selectedRecord && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <span className="font-medium text-muted-foreground">Status: </span>
                  <Badge variant={statusColor(selectedRecord.status)}>{selectedRecord.status}</Badge>
                </div>
                <div>
                  <span className="font-medium text-muted-foreground">Data da Publicação: </span>
                  {formatDate(selectedRecord.publication_date)}
                </div>
                {selectedRecord.creation_date && (
                  <div>
                    <span className="font-medium text-muted-foreground">Data de Captura (Ajus): </span>
                    {formatDate(selectedRecord.creation_date)}
                  </div>
                )}
                <div>
                  <span className="font-medium text-muted-foreground">Processo: </span>
                  {selectedRecord.linked_lawsuit_cnj || selectedRecord.linked_lawsuit_id || "N/A"}
                </div>
                <div>
                  <span className="font-medium text-muted-foreground">Escritório: </span>
                  {officeName(selectedRecord.linked_office_id) || "N/A"}
                </div>
                {selectedRecord.category && (
                  <>
                    <div>
                      <span className="font-medium text-muted-foreground">Categoria: </span>
                      {selectedRecord.category}
                    </div>
                    <div>
                      <span className="font-medium text-muted-foreground">Subcategoria: </span>
                      {selectedRecord.subcategory || "-"}
                    </div>
                  </>
                )}
                {selectedRecord.classifications && selectedRecord.classifications.length > 1 && (
                  <div className="col-span-2">
                    <span className="font-medium text-muted-foreground">Classificações adicionais: </span>
                    <div className="mt-1 space-y-1">
                      {selectedRecord.classifications.slice(1).map((c, i) => (
                        <div key={i} className="rounded border bg-muted/30 px-2 py-1 text-xs">
                          <span className="font-medium">{c.categoria}</span>
                          {c.subcategoria && c.subcategoria !== "-" && (
                            <span className="text-muted-foreground"> / {c.subcategoria}</span>
                          )}
                          {c.polo && (() => {
                            const info = poloLabel(c.polo);
                            return info ? (
                              <span className={`ml-2 inline-flex rounded border px-1 py-0 text-[10px] font-medium ${info.className}`}>
                                {info.label}
                              </span>
                            ) : null;
                          })()}
                          {c.confianca && (
                            <span className="ml-2 text-muted-foreground">({c.confianca})</span>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {selectedRecord.polo && (() => {
                  const info = poloLabel(selectedRecord.polo);
                  return info ? (
                    <div className="col-span-2">
                      <span className="font-medium text-muted-foreground">Polo: </span>
                      <span
                        className={`inline-flex rounded border px-2 py-0.5 text-xs font-medium ${info.className}`}>
                        {info.label}
                      </span>
                    </div>
                  ) : null;
                })()}
                {selectedRecord.audiencia_data && (
                  <div className="col-span-2">
                    <span className="font-medium text-muted-foreground">Audiência: </span>
                    <span className="inline-flex items-center gap-1 rounded border border-violet-300 bg-violet-50 px-2 py-0.5 text-xs font-semibold text-violet-800">
                      <Calendar className="h-3 w-3" />
                      {new Date(selectedRecord.audiencia_data + "T12:00:00").toLocaleDateString("pt-BR")}
                      {selectedRecord.audiencia_hora && (
                        <span className="ml-1">às {selectedRecord.audiencia_hora}</span>
                      )}
                    </span>
                  </div>
                )}
                {selectedRecord.audiencia_link && (
                  <div className="col-span-2">
                    <span className="font-medium text-muted-foreground">Link audiência: </span>
                    <a href={selectedRecord.audiencia_link} target="_blank" rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 rounded border border-blue-300 bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700 hover:underline">
                      <Link2 className="h-3 w-3" />
                      {selectedRecord.audiencia_link.length > 50
                        ? selectedRecord.audiencia_link.slice(0, 50) + "..."
                        : selectedRecord.audiencia_link}
                      <ExternalLink className="h-3 w-3" />
                    </a>
                  </div>
                )}
              </div>
              <div>
                <Label className="text-muted-foreground">Texto da Publicação</Label>
                <ScrollArea className="mt-1 h-[200px] rounded border p-3">
                  <p className="whitespace-pre-wrap text-sm">
                    {selectedRecord.description || "Sem texto disponível."}
                  </p>
                </ScrollArea>
              </div>
              {selectedRecord.notes && (
                <div>
                  <Label className="text-muted-foreground">Observações</Label>
                  <p className="mt-1 text-sm">{selectedRecord.notes}</p>
                </div>
              )}
              <div className="flex gap-2 pt-2">
                {selectedRecord.status !== "AGENDADO" && selectedRecord.status !== "IGNORADO" && (
                  <Button size="sm" variant="outline"
                    onClick={() => { handleIgnoreRecord(selectedRecord.id); setDetailOpen(false); }}>
                    <EyeOff className="mr-1 h-3.5 w-3.5" />
                    Ignorar publicação
                  </Button>
                )}
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* ─── Duplicate Divergences Section ─────────────────────────────── */}
      <Card className="border-yellow-200">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <button
                type="button"
                className="flex items-center gap-2 text-base font-semibold hover:text-yellow-700 transition-colors"
                onClick={() => {
                  if (!showDuplicates) { setShowDuplicates(true); loadDuplicates(); }
                  else setShowDuplicates(false);
                }}
              >
                {showDuplicates ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                Registros Duplicados com Textos Divergentes
              </button>
              {duplicates && (
                <Badge variant="outline" className="text-yellow-700">
                  {duplicates.total} par{duplicates.total !== 1 ? "es" : ""}
                </Badge>
              )}
            </div>
            {showDuplicates && (
              <Button variant="ghost" size="sm" onClick={loadDuplicates} disabled={loadingDuplicates}>
                <RefreshCw className={`h-3.5 w-3.5 ${loadingDuplicates ? "animate-spin" : ""}`} />
              </Button>
            )}
          </div>
          <CardDescription>
            Pares de registros com o mesmo <code className="rounded bg-muted px-1 text-xs">legal_one_update_id</code>{" "}
            mas textos divergentes. Útil para identificar atualizações parciais ou registros corrompidos.
          </CardDescription>
        </CardHeader>

        {showDuplicates && (
          <CardContent className="pt-0">
            {loadingDuplicates ? (
              <div className="flex h-24 items-center justify-center gap-2 text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Carregando divergências...
              </div>
            ) : !duplicates || duplicates.divergences.length === 0 ? (
              <div className="rounded-md border bg-muted/30 p-6 text-center text-sm text-muted-foreground">
                Nenhum par duplicado com texto divergente encontrado. ✓
              </div>
            ) : (
              <div className="space-y-3">
                <p className="text-xs text-muted-foreground">
                  Mostrando {duplicates.divergences.length} de {duplicates.total} par{duplicates.total !== 1 ? "es" : ""}.
                </p>
                <ScrollArea className="max-h-[480px] rounded-md border">
                  <div className="divide-y">
                    {duplicates.divergences.map((pair) => (
                      <div key={pair.legal_one_update_id} className="p-4">
                        <div className="mb-2 flex items-center gap-2 text-xs text-muted-foreground">
                          <Badge variant="outline" className="font-mono text-[10px]">
                            update_id: {pair.legal_one_update_id}
                          </Badge>
                          <span>{formatDate(pair.original.publication_date)}</span>
                          <Badge variant={statusColor(pair.original.status)} className="text-[10px]">
                            original: {pair.original.status}
                          </Badge>
                          <Badge variant={statusColor(pair.duplicate.status)} className="text-[10px]">
                            duplicado: {pair.duplicate.status}
                          </Badge>
                        </div>
                        <div className="grid grid-cols-2 gap-3">
                          <div>
                            <p className="mb-1 text-[11px] font-medium text-muted-foreground">
                              Original (ID {pair.original.id})
                            </p>
                            <p className="rounded bg-muted/50 p-2 text-xs leading-relaxed">
                              {pair.original.description_preview}
                            </p>
                          </div>
                          <div>
                            <p className="mb-1 text-[11px] font-medium text-yellow-600">
                              Duplicado (ID {pair.duplicate.id})
                            </p>
                            <p className="rounded bg-yellow-50 border border-yellow-200 p-2 text-xs leading-relaxed">
                              {pair.duplicate.description_preview}
                            </p>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </ScrollArea>
              </div>
            )}
          </CardContent>
        )}
      </Card>

      {/* Schedule Dialog */}
      <Dialog open={scheduleOpen} onOpenChange={setScheduleOpen}>
        <DialogContent className="flex max-h-[90vh] max-w-2xl flex-col gap-0 p-0">
          {/* ── Header fixo ── */}
          <div className="border-b px-6 py-4">
            <DialogTitle className="flex items-center gap-2 text-base font-semibold">
              <Send className="h-4 w-4 text-primary" />
              Confirmar Agendamento
            </DialogTitle>
            <DialogDescription className="mt-1 text-sm">
              {scheduleGroup?.lawsuit_cnj
                ? <>Processo <span className="font-medium text-foreground">{scheduleGroup.lawsuit_cnj}</span></>
                : scheduleGroup?.lawsuit_id
                ? <>Processo <span className="font-medium text-foreground">#{scheduleGroup.lawsuit_id}</span></>
                : "Publicações sem processo vinculado"
              }
              {" · "}{scheduleGroup?.records.length ?? 0} publicação(ões)
            </DialogDescription>
          </div>

          {/* ── Corpo scrollável ── */}
          <div className="flex-1 overflow-y-auto px-6 py-4">
            {scheduleGroup && (
              <div className="space-y-5">

                {/* Texto da publicação */}
                <div>
                  <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    Texto da publicação
                  </p>
                  <div className="max-h-48 overflow-y-auto rounded-md border bg-muted/20 p-3">
                    {scheduleGroup.records.map((r, ri) => (
                      <div key={r.id} className={ri > 0 ? "mt-3 border-t pt-3" : ""}>
                        {scheduleGroup.records.length > 1 && (
                          <p className="mb-1 text-[10px] font-medium text-muted-foreground">
                            Publicação {ri + 1} — {r.description_preview || r.legal_one_update_id}
                          </p>
                        )}
                        <p className="whitespace-pre-wrap text-xs leading-relaxed text-foreground/80">
                          {r.description || r.description_preview || "Sem texto disponível."}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Publicações incluídas */}
                <div>
                  <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    Publicações incluídas
                  </p>
                  <div className="space-y-1 rounded-md border bg-muted/30 p-2">
                    {scheduleGroup.records.map((r) => (
                      <div key={r.id} className="flex items-center gap-2 text-xs">
                        <Badge variant={statusColor(r.status)} className="shrink-0">{r.status}</Badge>
                        <span className="min-w-0 flex-1 truncate text-muted-foreground">
                          {r.description_preview || r.legal_one_update_id}
                        </span>
                        <span className="shrink-0 tabular-nums text-muted-foreground">
                          {formatDateShort(r.publication_date)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>

                <Separator />

                {/* Aviso de audiência */}
                {(() => {
                  const audRec = scheduleGroup.records.find((r) => r.audiencia_data);
                  if (!audRec) return null;
                  return (
                    <div className="flex items-start gap-3 rounded-md border border-violet-200 bg-violet-50 p-3">
                      <Calendar className="mt-0.5 h-4 w-4 shrink-0 text-violet-600" />
                      <div>
                        <p className="text-sm font-semibold text-violet-800">Audiência identificada</p>
                        <p className="text-xs text-violet-700">
                          Data e horário extraídos automaticamente. Verifique antes de confirmar.
                        </p>
                      </div>
                    </div>
                  );
                })()}

                {/* Tarefas propostas */}
                {editedPayloads.length > 0 ? (
                  <div className="space-y-4">
                    <p className="flex items-center gap-1.5 text-sm font-medium text-emerald-700">
                      <span className="flex h-4 w-4 items-center justify-center rounded-full bg-emerald-100 text-[10px] font-bold text-emerald-700">✓</span>
                      {editedPayloads.length} tarefa(s) a enviar — revise e confirme
                    </p>

                    {editedPayloads.map((payload, idx) => {
                      const isRemoved = removedTaskIndices.has(idx);
                      return (
                        <div
                          key={idx}
                          className={`rounded-lg border bg-background shadow-sm transition-opacity ${
                            isRemoved ? "opacity-40" : ""
                          }`}
                        >
                          {/* Cabeçalho do bloco */}
                          <div className="flex items-center justify-between rounded-t-lg border-b bg-muted/40 px-4 py-2">
                            <span className="text-xs font-semibold text-muted-foreground">
                              Tarefa {idx + 1}
                              {payload.template_name && (
                                <span className="ml-2 font-normal text-muted-foreground/70">
                                  · {payload.template_name}
                                </span>
                              )}
                            </span>
                            <Button
                              variant="ghost"
                              size="sm"
                              className={`h-6 px-2 text-xs ${isRemoved ? "text-emerald-600" : "text-destructive hover:text-destructive"}`}
                              onClick={() => {
                                const next = new Set(removedTaskIndices);
                                if (isRemoved) next.delete(idx); else next.add(idx);
                                setRemovedTaskIndices(next);
                              }}
                            >
                              {isRemoved ? "Restaurar" : "Remover"}
                            </Button>
                          </div>

                          {/* Campos do bloco */}
                          {!isRemoved && (() => {
                            // Subtipo selecionado e tipo associado (lookup nas metas)
                            const currentSubId = payload.subTypeId ?? null;
                            const parentType = taskTypes.find((t) =>
                              t.subtypes.some((s) => s.external_id === currentSubId)
                            ) || null;
                            // Responsável atual = primeiro participant com isResponsible (ou suggested)
                            const currentResp = (payload.participants || []).find(
                              (p: any) => p?.isResponsible
                            );
                            const currentRespId: number | null =
                              currentResp?.contact?.id ?? null;
                            return (
                              <div className="space-y-3 p-4">
                                <div className="grid gap-1.5">
                                  <Label className="text-xs font-medium">Descrição *</Label>
                                  <Textarea
                                    rows={2}
                                    className="resize-none text-sm"
                                    value={payload.description ?? ""}
                                    onChange={(e) => {
                                      const next = [...editedPayloads];
                                      next[idx] = { ...next[idx], description: e.target.value };
                                      setEditedPayloads(next);
                                    }}
                                  />
                                  <p className="text-[10px] text-muted-foreground">
                                    Máx. 250 caracteres ({(payload.description ?? "").length}/250)
                                  </p>
                                </div>

                                {/* Subtipo de tarefa */}
                                <div className="grid gap-1.5">
                                  <Label className="text-xs font-medium">Subtipo de tarefa *</Label>
                                  <Select
                                    value={currentSubId ? String(currentSubId) : ""}
                                    onValueChange={(v) => {
                                      const newSubId = parseInt(v, 10);
                                      const newType = taskTypes.find((t) =>
                                        t.subtypes.some((s) => s.external_id === newSubId)
                                      );
                                      const next = [...editedPayloads];
                                      next[idx] = {
                                        ...next[idx],
                                        subTypeId: newSubId,
                                        typeId: newType?.external_id ?? next[idx].typeId,
                                      };
                                      setEditedPayloads(next);
                                    }}
                                  >
                                    <SelectTrigger className="text-sm">
                                      <SelectValue placeholder="Selecione o subtipo" />
                                    </SelectTrigger>
                                    <SelectContent className="max-h-72">
                                      {taskTypes.map((t) => (
                                        <div key={t.external_id}>
                                          <div className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                                            {t.name}
                                          </div>
                                          {t.subtypes.map((s) => (
                                            <SelectItem
                                              key={s.external_id}
                                              value={String(s.external_id)}
                                            >
                                              {s.name}
                                            </SelectItem>
                                          ))}
                                        </div>
                                      ))}
                                    </SelectContent>
                                  </Select>
                                  {parentType && (
                                    <p className="text-[10px] text-muted-foreground">
                                      Tipo: {parentType.name}
                                    </p>
                                  )}
                                </div>

                                {/* Responsável */}
                                <div className="grid gap-1.5">
                                  <Label className="text-xs font-medium">Responsável *</Label>
                                  <Select
                                    value={currentRespId ? String(currentRespId) : ""}
                                    onValueChange={(v) => {
                                      const userId = parseInt(v, 10);
                                      const next = [...editedPayloads];
                                      next[idx] = {
                                        ...next[idx],
                                        participants: [{
                                          contact: { id: userId },
                                          isResponsible: true,
                                          isExecuter: true,
                                          isRequester: true,
                                        }],
                                      };
                                      setEditedPayloads(next);
                                    }}
                                  >
                                    <SelectTrigger className="text-sm">
                                      <SelectValue placeholder="Selecione um usuário" />
                                    </SelectTrigger>
                                    <SelectContent className="max-h-72">
                                      {appUsers.map((u) => (
                                        <SelectItem
                                          key={u.external_id}
                                          value={String(u.external_id)}
                                        >
                                          {u.name}
                                          {u.email && (
                                            <span className="ml-1 text-muted-foreground">
                                              · {u.email}
                                            </span>
                                          )}
                                        </SelectItem>
                                      ))}
                                    </SelectContent>
                                  </Select>
                                  {payload.suggested_responsible &&
                                    payload.suggested_responsible.id !== currentRespId && (
                                      <button
                                        type="button"
                                        className="self-start text-[10px] text-blue-700 underline hover:text-blue-900"
                                        onClick={() => {
                                          const next = [...editedPayloads];
                                          next[idx] = {
                                            ...next[idx],
                                            participants: [{
                                              contact: { id: payload.suggested_responsible!.id },
                                              isResponsible: true,
                                              isExecuter: true,
                                              isRequester: true,
                                            }],
                                          };
                                          setEditedPayloads(next);
                                        }}
                                      >
                                        Usar sugerido: {payload.suggested_responsible.name}
                                      </button>
                                    )}
                                </div>

                                {/* Escritório responsável */}
                                <div className="grid gap-1.5">
                                  <Label className="text-xs font-medium">Escritório responsável</Label>
                                  <Select
                                    value={
                                      payload.responsibleOfficeId
                                        ? String(payload.responsibleOfficeId)
                                        : "_none"
                                    }
                                    onValueChange={(v) => {
                                      const next = [...editedPayloads];
                                      next[idx] = {
                                        ...next[idx],
                                        responsibleOfficeId:
                                          v === "_none" ? null : parseInt(v, 10),
                                      };
                                      setEditedPayloads(next);
                                    }}
                                  >
                                    <SelectTrigger className="text-sm">
                                      <SelectValue placeholder="—" />
                                    </SelectTrigger>
                                    <SelectContent className="max-h-72">
                                      <SelectItem value="_none">— Não definir —</SelectItem>
                                      {offices.map((o) => (
                                        <SelectItem
                                          key={o.external_id}
                                          value={String(o.external_id)}
                                        >
                                          {officeLabel(o)}
                                        </SelectItem>
                                      ))}
                                    </SelectContent>
                                  </Select>
                                </div>

                                <div className="grid grid-cols-12 gap-3">
                                  <div className="col-span-5 grid gap-1.5">
                                    <Label className="text-xs font-medium">
                                      {scheduleGroup.records.some((r) => r.audiencia_data)
                                        ? "Data da Audiência *"
                                        : "Prazo / Data"}
                                    </Label>
                                    <Input
                                      type="date"
                                      className="text-sm"
                                      value={payload.endDateTime?.slice(0, 10) ?? ""}
                                      onChange={(e) => {
                                        const newDate = e.target.value;
                                        const currentIso = payload.endDateTime ?? "";
                                        const time = currentIso.slice(11, 19) || "23:59:59";
                                        const iso = `${newDate}T${time}Z`;
                                        const next = [...editedPayloads];
                                        next[idx] = { ...next[idx], endDateTime: iso, startDateTime: iso };
                                        setEditedPayloads(next);
                                      }}
                                    />
                                  </div>
                                  <div className="col-span-3 grid gap-1.5">
                                    <Label className="text-xs font-medium">Horário</Label>
                                    <Input
                                      type="time"
                                      step={60}
                                      className="text-sm"
                                      value={payload.endDateTime?.slice(11, 16) ?? ""}
                                      onChange={(e) => {
                                        const newTime = e.target.value || "23:59";
                                        const currentIso = payload.endDateTime ?? "";
                                        const date = currentIso.slice(0, 10) ||
                                          new Date().toISOString().slice(0, 10);
                                        const iso = `${date}T${newTime}:00Z`;
                                        const next = [...editedPayloads];
                                        next[idx] = { ...next[idx], endDateTime: iso, startDateTime: iso };
                                        setEditedPayloads(next);
                                      }}
                                    />
                                  </div>
                                  <div className="col-span-4 grid gap-1.5">
                                    <Label className="text-xs font-medium">Prioridade</Label>
                                    <Select
                                      value={payload.priority ?? "Normal"}
                                      onValueChange={(v) => {
                                        const next = [...editedPayloads];
                                        next[idx] = { ...next[idx], priority: v };
                                        setEditedPayloads(next);
                                      }}
                                    >
                                      <SelectTrigger className="text-sm"><SelectValue /></SelectTrigger>
                                      <SelectContent>
                                        <SelectItem value="Low">Baixa</SelectItem>
                                        <SelectItem value="Normal">Normal</SelectItem>
                                        <SelectItem value="High">Alta</SelectItem>
                                      </SelectContent>
                                    </Select>
                                  </div>
                                </div>
                                {scheduleGroup.records.some((r) => r.audiencia_data) && (
                                  <p className="text-[10px] text-violet-700">
                                    Audiência detectada — confirme o horário extraído da publicação.
                                  </p>
                                )}

                                <div className="grid gap-1.5">
                                  <Label className="text-xs font-medium">Observações</Label>
                                  <Textarea
                                    rows={3}
                                    className="resize-none text-sm"
                                    placeholder="Opcional"
                                    value={payload.notes ?? ""}
                                    onChange={(e) => {
                                      const next = [...editedPayloads];
                                      next[idx] = { ...next[idx], notes: e.target.value || null };
                                      setEditedPayloads(next);
                                    }}
                                  />
                                </div>
                              </div>
                            );
                          })()}
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <Alert>
                    <AlertCircle className="h-4 w-4" />
                    <AlertTitle>Sem template configurado</AlertTitle>
                    <AlertDescription>
                      Não há template para a classificação deste processo.{" "}
                      <Link to="/publications/templates" className="font-medium underline">
                        Configurar templates
                      </Link>{" "}
                      para habilitar o agendamento automático.
                    </AlertDescription>
                  </Alert>
                )}
              </div>
            )}
          </div>

          {/* ── Footer fixo ── */}
          <div className="flex items-center justify-end gap-3 border-t bg-background px-6 py-4">
            <Button variant="outline" onClick={() => setScheduleOpen(false)} disabled={scheduling}>
              Cancelar
            </Button>
            <Button
              onClick={handleConfirmSchedule}
              disabled={scheduling || editedPayloads.length === 0 || removedTaskIndices.size === editedPayloads.length}
            >
              {scheduling
                ? <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                : <Send className="mr-2 h-4 w-4" />}
              Enviar {editedPayloads.length - removedTaskIndices.size} tarefa(s)
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Save Filter Dialog */}
      <Dialog open={isSaveFilterDialogOpen} onOpenChange={setIsSaveFilterDialogOpen}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Salvar Filtros Atuais</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label htmlFor="filter-name">Nome do Filtro</Label>
              <Input
                id="filter-name"
                value={filterName}
                onChange={(e) => setFilterName(e.target.value)}
                placeholder="Ex: Novos do Escritório SP"
              />
            </div>
            <div className="flex items-center gap-2">
              <Checkbox
                id="is-default"
                checked={isFilterDefault}
                onCheckedChange={(c) => setIsFilterDefault(!!c)}
              />
              <Label htmlFor="is-default" className="font-normal cursor-pointer">
                Marcar como filtro padrão
              </Label>
            </div>
          </div>
          <DialogFooter>
            <Button variant="secondary" onClick={() => setIsSaveFilterDialogOpen(false)}>
              Cancelar
            </Button>
            <Button onClick={handleSaveFilter} disabled={isSavingFilter}>
              {isSavingFilter && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Salvar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ─── Dialog: Feedback explícito (thumbs-down) ─────────────── */}
      <Dialog open={feedbackOpen} onOpenChange={setFeedbackOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <MessageSquareWarning className="h-5 w-5 text-red-500" />
              Reportar classificação errada
            </DialogTitle>
            <DialogDescription>
              Corrija a classificação e, opcionalmente, adicione uma nota. O classificador aprenderá com esse feedback.
            </DialogDescription>
          </DialogHeader>

          {feedbackRecord && (
            <div className="space-y-4">
              {/* Classificação atual (errada) */}
              <div className="rounded-md border border-red-200 bg-red-50 p-3">
                <p className="text-xs font-medium text-red-700 mb-1">Classificação atual</p>
                <p className="text-sm font-semibold">
                  {feedbackRecord.category || "—"}
                  {feedbackRecord.subcategory && feedbackRecord.subcategory !== "-"
                    ? ` → ${feedbackRecord.subcategory}`
                    : ""}
                </p>
                {feedbackRecord.polo && (
                  <p className="text-xs text-red-600">Polo: {feedbackRecord.polo}</p>
                )}
              </div>

              {/* Tipo de erro */}
              <div className="space-y-1">
                <Label className="text-xs">O que estava errado?</Label>
                <Select value={feedbackErrorType} onValueChange={setFeedbackErrorType}>
                  <SelectTrigger className="h-8 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="category">Categoria</SelectItem>
                    <SelectItem value="subcategory">Subcategoria</SelectItem>
                    <SelectItem value="polo">Polo</SelectItem>
                    <SelectItem value="natureza">Natureza do processo</SelectItem>
                    <SelectItem value="multiple">Vários campos</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {/* Classificação correta */}
              <div className="space-y-1">
                <Label className="text-xs">Classificação correta</Label>
                <Select
                  value={feedbackSubcategory ? `${feedbackCategory}|||${feedbackSubcategory}` : feedbackCategory}
                  onValueChange={(v) => {
                    const [cat, sub] = v.split("|||");
                    setFeedbackCategory(cat);
                    setFeedbackSubcategory(sub || "");
                  }}
                >
                  <SelectTrigger className="h-8 text-xs">
                    <SelectValue placeholder="Selecione a classificação correta" />
                  </SelectTrigger>
                  <SelectContent className="max-h-80">
                    {Object.entries(taxonomy).map(([cat, subs]) => (
                      <div key={cat}>
                        {subs && subs.length > 0 ? (
                          <>
                            <div className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                              {cat}
                            </div>
                            {subs.map((sub) => (
                              <SelectItem key={`${cat}|||${sub}`} value={`${cat}|||${sub}`}>
                                {sub}
                              </SelectItem>
                            ))}
                          </>
                        ) : (
                          <SelectItem value={cat}>{cat}</SelectItem>
                        )}
                      </div>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {/* Polo correto */}
              <div className="space-y-1">
                <Label className="text-xs">Polo correto</Label>
                <Select value={feedbackPolo} onValueChange={setFeedbackPolo}>
                  <SelectTrigger className="h-8 text-xs">
                    <SelectValue placeholder="Selecione o polo" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="ativo">Ativo</SelectItem>
                    <SelectItem value="passivo">Passivo</SelectItem>
                    <SelectItem value="ambos">Ambos</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {/* Natureza (só para sem processo) */}
              {!feedbackRecord.linked_lawsuit_id && (
                <div className="space-y-1">
                  <Label className="text-xs">Natureza do processo</Label>
                  <Input
                    className="h-8 text-xs"
                    placeholder="Ex.: Embargos à Execução, Agravo de Instrumento..."
                    value={feedbackNatureza}
                    onChange={(e) => setFeedbackNatureza(e.target.value)}
                  />
                </div>
              )}

              {/* Nota do operador */}
              <div className="space-y-1">
                <Label className="text-xs">Nota / regra (opcional)</Label>
                <Textarea
                  className="text-xs min-h-[60px]"
                  placeholder="Ex.: 'Quando menciona embargante, sempre é Embargos à Execução'"
                  value={feedbackNote}
                  onChange={(e) => setFeedbackNote(e.target.value)}
                />
                <p className="text-[10px] text-muted-foreground">
                  Dica: descreva uma regra geral para que o classificador aprenda com essa correção.
                </p>
              </div>
            </div>
          )}

          <DialogFooter>
            <Button variant="secondary" onClick={() => setFeedbackOpen(false)} disabled={submittingFeedback}>
              Cancelar
            </Button>
            <Button onClick={handleSubmitFeedback} disabled={submittingFeedback}>
              {submittingFeedback && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Enviar feedback
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default PublicationsPage;
