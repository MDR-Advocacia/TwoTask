// Conteúdo para: frontend/src/pages/CreateTaskFromSpreadsheetPage.tsx

import { useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/hooks/use-toast";
import { Upload, File, AlertCircle, Loader2 } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';

const CreateTaskFromSpreadsheetPage = () => {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { toast } = useToast();

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

    const formData = new FormData();
    formData.append('file', selectedFile);

    try {
      const response = await fetch('/api/v1/tasks/batch-create-from-spreadsheet', {
        method: 'POST',
        body: formData,
      });

      if (response.status !== 202) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Ocorreu uma falha ao enviar o arquivo.');
      }

      toast({
        title: "Arquivo Enviado!",
        description: "Sua planilha foi recebida e está sendo processada em segundo plano.",
      });

      setSelectedFile(null); // Limpa o campo após o envio
    } catch (err) {
        const errorMessage = err instanceof Error ? err.message : "Erro desconhecido.";
        setError(errorMessage);
        toast({
            title: "Erro no Envio",
            description: errorMessage,
            variant: "destructive",
        });
    } finally {
      setIsSubmitting(false);
    }
  };

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
            {isSubmitting ? 'Enviando...' : 'Enviar e Processar'}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
};

export default CreateTaskFromSpreadsheetPage;