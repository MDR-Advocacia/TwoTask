import { useState, useEffect } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/hooks/use-toast";
import { Upload, File, AlertCircle, Loader2, CheckCircle2 } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';

// --- NOVOS IMPORTS DO SHADCN ---
import { Progress } from "@/components/ui/progress";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
} from "@/components/ui/alert-dialog";

const CreateTaskFromSpreadsheetPage = () => {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { toast } = useToast();

  // --- NOVOS ESTADOS PARA O PROGRESSO ---
  const [batchId, setBatchId] = useState<number | null>(null);
  const [progress, setProgress] = useState(0);
  const [processedCount, setProcessedCount] = useState(0);
  const [totalCount, setTotalCount] = useState(0);
  const [isMonitoring, setIsMonitoring] = useState(false);

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) {
      if (file.type === "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet") {
        setSelectedFile(file);
        setError(null);
      } else {
        setError("Formato de arquivo inválido. Por favor, selecione um arquivo .xlsx.");
        setSelectedFile(null);
      }
    }
  };

  const handleSubmit = async () => {
    if (!selectedFile) {
      setError("Nenhum arquivo selecionado.");
      return;
    }
    setIsSubmitting(true);
    setError(null);
    setProgress(0); // Reseta visualmente

    const formData = new FormData();
    formData.append('file', selectedFile);

    try {
      // 1. Envia o arquivo e espera o ID do lote
      const response = await fetch('/api/v1/tasks/batch-create-from-spreadsheet', {
        method: 'POST',
        body: formData,
      });

      if (response.status !== 202) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Ocorreu uma falha ao enviar o arquivo.');
      }

      const data = await response.json();

      // 2. Se o backend retornou o ID, inicia o monitoramento
      if (data.batch_id) {
          setBatchId(data.batch_id);
          setIsMonitoring(true);
          // O toast de "sucesso" final será exibido quando o polling terminar
      } else {
          // Fallback de segurança (caso o backend não retorne ID)
          toast({
            title: "Arquivo Enviado!",
            description: "Processamento iniciado em segundo plano.",
          });
          setIsSubmitting(false);
          setSelectedFile(null);
      }

    } catch (err) {
        const errorMessage = err instanceof Error ? err.message : "Erro desconhecido.";
        setError(errorMessage);
        toast({
            title: "Erro no Envio",
            description: errorMessage,
            variant: "destructive",
        });
        setIsSubmitting(false);
    }
  };

  // --- EFEITO DE POLLING (CONSULTA DE STATUS) ---
  useEffect(() => {
    let intervalId: NodeJS.Timeout;

    if (isMonitoring && batchId) {
      intervalId = setInterval(async () => {
        try {
          // Consulta o endpoint de status (criado no tasks.py)
          const res = await fetch(`/api/v1/tasks/batch/status/${batchId}`);
          if (!res.ok) return;

          const data = await res.json();
          
          setProgress(data.percentage);
          setProcessedCount(data.processed_items);
          setTotalCount(data.total_items);

          // Condição de parada: Status CONCLUIDO ou 100% processado
          if (data.status === 'CONCLUIDO' || (data.total_items > 0 && data.processed_items === data.total_items)) {
              clearInterval(intervalId);
              
              // Pequeno delay para o usuário ver a barra cheia (100%)
              setTimeout(() => {
                  setIsMonitoring(false);
                  setIsSubmitting(false);
                  setSelectedFile(null);
                  setBatchId(null);
                  
                  toast({
                      title: "Processamento Finalizado!",
                      description: `${data.processed_items} tarefas processadas.`,
                      className: "bg-green-50 border-green-200"
                  });
              }, 1500);
          }

        } catch (error) {
            console.error("Erro ao buscar status do lote:", error);
        }
      }, 1500); // Consulta a cada 1.5 segundos
    }

    return () => clearInterval(intervalId);
  }, [isMonitoring, batchId, toast]);

  return (
    <div className="container mx-auto px-6 py-8">
      <div className="mb-8">
        <h1 className="text-3xl font-bold bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
          Criação de Tarefas por Planilha
        </h1>
        <p className="text-muted-foreground mt-1">
          Faça o upload de um arquivo .xlsx para agendar tarefas em lote.
        </p>
      </div>
      
      <Card className="max-w-2xl mx-auto glass-card border-0 animate-fade-in">
        <CardHeader>
          <CardTitle>Upload de Planilha</CardTitle>
          <CardDescription>
            Selecione o arquivo .xlsx contendo as tarefas a serem criadas.
            O arquivo deve conter as colunas: CNJ, ID_RESPONSAVEL, OBSERVACAO.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="grid w-full items-center gap-1.5">
            <Label htmlFor="spreadsheet-file">Arquivo Excel</Label>
            <div className="flex items-center gap-3">
              <Input
                id="spreadsheet-file"
                type="file"
                accept=".xlsx"
                onChange={handleFileChange}
                disabled={isSubmitting} // Bloqueia input durante o processo
                className="file:text-primary file:font-medium"
              />
            </div>
          </div>

          {selectedFile && (
            <div className="flex items-center p-3 rounded-md bg-muted/50">
              <File className="w-5 h-5 mr-3 text-primary" />
              <span className="text-sm font-medium">{selectedFile.name}</span>
            </div>
          )}

          {error && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>Erro</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          <Button 
            onClick={handleSubmit} 
            disabled={!selectedFile || isSubmitting}
            className="w-full glass-button text-white"
          >
            {isSubmitting ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Upload className="mr-2 h-4 w-4" />
            )}
            {isSubmitting ? 'Processando...' : 'Enviar e Processar'}
          </Button>
        </CardContent>
      </Card>

      {/* --- COMPONENTE POPUP DE PROGRESSO --- */}
      <AlertDialog open={isMonitoring}>
        <AlertDialogContent className="sm:max-w-md">
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2">
              {progress === 100 ? (
                <CheckCircle2 className="h-6 w-6 text-green-500" />
              ) : (
                <Loader2 className="h-6 w-6 animate-spin text-blue-500" />
              )}
              {progress === 100 ? "Concluído!" : "Criando Tarefas..."}
            </AlertDialogTitle>
            <AlertDialogDescription>
              Aguarde enquanto o sistema processa sua planilha e cria as tarefas no Legal One.
              <br />
              <span className="text-xs text-muted-foreground mt-1 block">
                Não feche esta janela.
              </span>
            </AlertDialogDescription>
          </AlertDialogHeader>

          <div className="py-6 space-y-4">
            {/* Barra de Progresso Visual */}
            <Progress value={progress} className="w-full h-4" />
            
            <div className="flex justify-between text-sm text-gray-500 font-medium">
              <span>{progress}%</span>
              <span>{processedCount} / {totalCount}</span>
            </div>
            
            <p className="text-xs text-center text-gray-400">
               {progress < 100 ? "Validando dados e enviando para API..." : "Finalizando..."}
            </p>
          </div>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
};

export default CreateTaskFromSpreadsheetPage;