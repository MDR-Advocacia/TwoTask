import { useState, useEffect, useMemo } from 'react';
import Layout from '@/components/Layout';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { useToast } from '@/hooks/use-toast';
import { Loader2, Search } from 'lucide-react';

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import UserSelector, { SelectableUser } from '@/components/ui/UserSelector'; // Importando o novo componente

// --- Interfaces ---
interface Lawsuit {
  id: number;
  identifierNumber: string;
  responsibleOfficeId?: number; // Adicionado para guardar o escritório do processo
}

interface TaskType {
  id: number;
  name: string;
}

interface TaskSubType {
  id: number;
  name: string;
  parentTypeId: number;
  squad_ids: number[]; // Squads associados a este subtipo
}

const TaskCreationPage = () => {
  const { toast } = useToast();
  const [cnj, setCnj] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const [foundLawsuit, setFoundLawsuit] = useState<Lawsuit | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);

  // Estado para os dados do formulário
  const [taskTypes, setTaskTypes] = useState<TaskType[]>([]);
  const [subTypes, setSubTypes] = useState<TaskSubType[]>([]);
  const [users, setUsers] = useState<SelectableUser[]>([]); // Usando a interface do UserSelector
  const [isFormLoading, setIsFormLoading] = useState(true);

  // Estado dos campos do formulário
  const [selectedTaskTypeId, setSelectedTaskTypeId] = useState<string>('');
  const [selectedSubTypeId, setSelectedSubTypeId] = useState<string>('');
  const [selectedResponsibleId, setSelectedResponsibleId] = useState<string | null>(null); // Pode ser null
  const [description, setDescription] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  
  // Novos estados para data
  const [startDateTime, setStartDateTime] = useState(new Date());
  const [endDateTime, setEndDateTime] = useState(() => {
    const date = new Date();
    date.setHours(date.getHours() + 24);
    return date;
  });

  // Carregar dados usando o novo endpoint
  useEffect(() => {
    const fetchFormData = async () => {
      setIsFormLoading(true);
      try {
        const response = await fetch('/api/v1/tasks/task-creation-data');
        if (!response.ok) {
          throw new Error('Falha ao carregar os dados necessários para o formulário.');
        }
        const data = await response.json();
        setTaskTypes(data.task_types);
        setSubTypes(data.sub_types);
        setUsers(data.users);
      } catch (error) {
        const msg = error instanceof Error ? error.message : 'Erro desconhecido';
        toast({ title: 'Erro ao Carregar Dados', description: msg, variant: 'destructive' });
      } finally {
        setIsFormLoading(false);
      }
    };
    fetchFormData();
  }, [toast]);

  // Memoizando listas filtradas para otimização
  const filteredSubTypes = useMemo(() => {
    if (!selectedTaskTypeId) return [];
    return subTypes.filter(st => st.parentTypeId === parseInt(selectedTaskTypeId, 10));
  }, [selectedTaskTypeId, subTypes]);

  const squadIdsForFilter = useMemo(() => {
    if (!selectedSubTypeId) return [];
    const selectedSubType = subTypes.find(st => st.id === parseInt(selectedSubTypeId, 10));
    return selectedSubType?.squad_ids || [];
  }, [selectedSubTypeId, subTypes]);

  // Resetar seleções quando o tipo ou subtipo muda
  useEffect(() => {
    setSelectedSubTypeId('');
    setSelectedResponsibleId(null);
  }, [selectedTaskTypeId]);

  useEffect(() => {
    setSelectedResponsibleId(null);
  }, [selectedSubTypeId]);

  // Atualiza a data de fim se a de início mudar
  useEffect(() => {
    if (startDateTime) {
      const newEndDateTime = new Date(startDateTime.getTime());
      newEndDateTime.setHours(newEndDateTime.getHours() + 24);
      setEndDateTime(newEndDateTime);
    }
  }, [startDateTime]);


  const handleSubmit = async () => {
    // A validação do Tipo (selectedTaskTypeId) é removida pois o que importa para o payload é o subtipo, que contém o parentId.
    if (!foundLawsuit || !selectedSubTypeId || !selectedResponsibleId) {
      toast({
        title: 'Campos Obrigatórios',
        description: 'Tipo, subtipo e responsável são obrigatórios.',
        variant: 'destructive',
      });
      return;
    }

    if (endDateTime <= startDateTime) {
      toast({
        title: 'Data Inválida',
        description: 'A data de fim deve ser posterior à data de início.',
        variant: 'destructive',
      });
      return;
    }

    if (!foundLawsuit.responsibleOfficeId) {
      toast({
        title: 'Erro de Dados',
        description: 'O ID do escritório responsável não foi encontrado no processo. Não é possível continuar.',
        variant: 'destructive',
      });
      return;
    }

    setIsSubmitting(true);

    const selectedSubType = subTypes.find(st => st.id === parseInt(selectedSubTypeId, 10));

    if (!selectedSubType) {
      toast({ title: 'Erro Interno', description: 'O subtipo de tarefa selecionado não foi encontrado.', variant: 'destructive' });
      setIsSubmitting(false);
      return;
    }

    const task_payload = {
      subTypeId: parseInt(selectedSubTypeId, 10),
      description: description || 'Tarefa criada via sistema',
      priority: 'Normal',
      typeId: selectedSubType.parentTypeId, // Correção: Usar o parentTypeId do subtipo
      startDateTime: startDateTime.toISOString(),
      endDateTime: endDateTime.toISOString(),
      status: { id: 1 },
      originOfficeId: 1, // MDR Advocacia
      responsibleOfficeId: foundLawsuit.responsibleOfficeId,
      isResponsible: true,
      isExecuter: true,
      isRequester: true,
    };

    const requestBody = {
      cnj_number: foundLawsuit.identifierNumber,
      task_payload,
      participants: [], // A definição de papéis agora é feita no payload principal.
    };

    try {
      const response = await fetch('/api/v1/tasks/create-full-process', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestBody),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Falha ao criar a tarefa.');
      }

      const result = await response.json();
      toast({
        title: 'Tarefa Criada com Sucesso!',
        description: `A tarefa ID ${result.created_task.id} foi criada e vinculada ao processo.`,
      });

      // Limpa o formulário e o resultado da busca
      setFoundLawsuit(null);
      setCnj('');
      setSelectedTaskTypeId('');
      setSelectedSubTypeId('');
      setSelectedResponsibleId('');
      setDescription('');

    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Ocorreu um erro desconhecido.';
      toast({ title: 'Erro ao Criar Tarefa', description: errorMessage, variant: 'destructive' });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSearch = async () => {
    if (!cnj.trim()) {
      toast({ title: 'CNJ Inválido', description: 'Por favor, insira um número de CNJ.', variant: 'destructive' });
      return;
    }
    setIsSearching(true);
    setSearchError(null);
    setFoundLawsuit(null);

    try {
      const response = await fetch(`/api/v1/tasks/search-lawsuit?cnj=${encodeURIComponent(cnj)}`);
      if (!response.ok) {
        if (response.status === 404) {
          throw new Error('Nenhum processo encontrado com este CNJ.');
        }
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Falha ao buscar o processo.');
      }
      const data: Lawsuit = await response.json();
      setFoundLawsuit(data);
      toast({ title: 'Processo Encontrado!', description: `ID do Processo: ${data.id}` });
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Ocorreu um erro desconhecido.';
      setSearchError(errorMessage);
      toast({ title: 'Erro na Busca', description: errorMessage, variant: 'destructive' });
    } finally {
      setIsSearching(false);
    }
  };

  return (
    <Layout>
      <div className="container mx-auto py-10 space-y-8">
        {/* --- BANNER DE TESTE --- */}
        <div style={{ backgroundColor: 'yellow', color: 'black', padding: '1rem', textAlign: 'center', fontWeight: 'bold', fontSize: '1.2rem', border: '2px solid red' }}>
          VERSÃO DE TESTE - Se você está vendo este banner, as alterações foram aplicadas.
        </div>
        {/* --- FIM DO BANNER DE TESTE --- */}
        <div className="mb-8">
          <h1 className="text-3xl font-bold">Criação de Tarefas no Legal One</h1>
          <p className="text-muted-foreground">
            Busque um processo pelo número CNJ para iniciar a criação de uma nova tarefa.
          </p>
        </div>

        {/* Seção de Busca */}
        <Card>
          <CardHeader>
            <CardTitle>1. Buscar Processo</CardTitle>
            <CardDescription>
              Insira o número do CNJ para localizar o processo no Legal One.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-2">
              <Input
                placeholder="0000000-00.0000.0.00.0000"
                value={cnj}
                onChange={(e) => setCnj(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                disabled={isSearching}
              />
              <Button onClick={handleSearch} disabled={isSearching || !cnj.trim()}>
                {isSearching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                <span className="ml-2">Buscar</span>
              </Button>
            </div>
            {searchError && <p className="text-red-500 text-sm mt-2">{searchError}</p>}
          </CardContent>
        </Card>

        {/* Seção de Complemento */}
        {foundLawsuit && (
          <Card>
            <CardHeader>
              <CardTitle>2. Complementar Informações da Tarefa</CardTitle>
              <CardDescription>
                Processo encontrado: <strong>{foundLawsuit.identifierNumber}</strong> (ID: {foundLawsuit.id}). Agora, preencha os detalhes da tarefa.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                {/* Tipo de Tarefa */}
                <div className="space-y-2">
                  <Label htmlFor="task-type">Tipo de Tarefa</Label>
                  <Select value={selectedTaskTypeId} onValueChange={setSelectedTaskTypeId}>
                    <SelectTrigger id="task-type">
                      <SelectValue placeholder="Selecione o tipo..." />
                    </SelectTrigger>
                    <SelectContent>
                      {taskTypes.map(type => (
                        <SelectItem key={type.id} value={String(type.id)}>{type.name}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                {/* Subtipo de Tarefa */}
                <div className="space-y-2">
                  <Label htmlFor="sub-type">Subtipo de Tarefa</Label>
                  <Select value={selectedSubTypeId} onValueChange={setSelectedSubTypeId} disabled={!selectedTaskTypeId}>
                    <SelectTrigger id="sub-type">
                      <SelectValue placeholder="Selecione o subtipo..." />
                    </SelectTrigger>
                    <SelectContent>
                      {filteredSubTypes.map(subType => (
                        <SelectItem key={subType.id} value={String(subType.id)}>{subType.name}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                {/* Responsável com o novo UserSelector */}
                <div className="space-y-2">
                  <Label htmlFor="responsible">Responsável</Label>
                  <UserSelector
                    users={users}
                    value={selectedResponsibleId}
                    onChange={setSelectedResponsibleId}
                    filterBySquadIds={squadIdsForFilter}
                    disabled={!selectedSubTypeId || users.length === 0}
                  />
                  {squadIdsForFilter.length > 0 && (
                    <p className="text-xs text-muted-foreground">
                      Mostrando usuários dos squads associados a este subtipo.
                    </p>
                  )}
                </div>

                {/* Datas de Início e Fim */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="start-datetime">Data e Hora de Início</Label>
                    <Input
                      id="start-datetime"
                      type="datetime-local"
                      value={startDateTime.toISOString().slice(0, 16)}
                      onChange={(e) => setStartDateTime(new Date(e.target.value))}
                      className="bg-input"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="end-datetime">Data e Hora de Fim</Label>
                    <Input
                      id="end-datetime"
                      type="datetime-local"
                      value={endDateTime.toISOString().slice(0, 16)}
                      onChange={(e) => setEndDateTime(new Date(e.target.value))}
                      className="bg-input"
                    />
                  </div>
                </div>
                
                {/* Descrição */}
                <div className="space-y-2">
                  <Label htmlFor="description">Descrição</Label>
                  <Textarea
                    id="description"
                    placeholder="Insira a descrição da tarefa..."
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                  />
                </div>

                <div className="flex justify-end">
                  <Button onClick={handleSubmit} disabled={isSubmitting || !selectedSubTypeId || !selectedResponsibleId || isFormLoading}>
                    {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
                    Criar Tarefa
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </Layout>
  );
};

export default TaskCreationPage;