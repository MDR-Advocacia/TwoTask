import { useState } from 'react';
import Layout from '@/components/Layout';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { useToast } from '@/hooks/use-toast';
import { Loader2, Search } from 'lucide-react';

import { useEffect } from 'react';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';

// Define tipos para os dados que vamos manipular
interface Lawsuit {
  id: number;
  identifierNumber: string;
}

interface TaskType {
  id: number;
  name: string;
}

interface TaskSubType {
  id: number;
  name: string;
  parentTypeId: number;
}

interface LegalOneUser {
  id: number; // ID do usuário no nosso BD
  external_id: number; // ID do usuário no Legal One (usado como contact_id)
  name: string;
  email: string;
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
  const [users, setUsers] = useState<LegalOneUser[]>([]);
  const [filteredSubTypes, setFilteredSubTypes] = useState<TaskSubType[]>([]);

  // Estado dos campos do formulário
  const [selectedTaskTypeId, setSelectedTaskTypeId] = useState<string>('');
  const [selectedSubTypeId, setSelectedSubTypeId] = useState<string>('');
  const [selectedResponsibleId, setSelectedResponsibleId] = useState<string>('');
  const [description, setDescription] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Carregar dados para os seletores do formulário
  useEffect(() => {
    const fetchFormData = async () => {
      try {
        // Usaremos o endpoint que já agrupa tipos e subtipos
        const taskTypesResponse = await fetch('/api/v1/admin/task-types');
        const usersResponse = await fetch('/api/v1/squads/legal-one-users');

        if (!taskTypesResponse.ok || !usersResponse.ok) {
          throw new Error('Falha ao carregar dados para o formulário.');
        }

        const taskTypeGroups = await taskTypesResponse.json();
        const usersData = await usersResponse.json();

        // Achatando os grupos para listas simples de tipos e subtipos
        const allTypes = taskTypeGroups.map((group: any) => ({ id: group.parent_id, name: group.parent_name }));
        const allSubTypes = taskTypeGroups.flatMap((group: any) =>
          group.sub_types.map((st: any) => ({ ...st, parentTypeId: group.parent_id }))
        );

        setTaskTypes(allTypes);
        setSubTypes(allSubTypes);
        setUsers(usersData);
      } catch (error) {
        toast({ title: 'Erro ao carregar dados', description: error.message, variant: 'destructive' });
      }
    };
    fetchFormData();
  }, [toast]);

  // Filtrar subtipos quando um tipo de tarefa é selecionado
  useEffect(() => {
    if (selectedTaskTypeId) {
      const parentId = parseInt(selectedTaskTypeId, 10);
      setFilteredSubTypes(subTypes.filter(st => st.parentTypeId === parentId));
      setSelectedSubTypeId(''); // Reseta o subtipo selecionado
    } else {
      setFilteredSubTypes([]);
    }
  }, [selectedTaskTypeId, subTypes]);

  const handleSubmit = async () => {
    if (!foundLawsuit || !selectedSubTypeId || !selectedResponsibleId) {
      toast({
        title: 'Campos Obrigatórios',
        description: 'Tipo, subtipo e responsável são obrigatórios.',
        variant: 'destructive',
      });
      return;
    }

    setIsSubmitting(true);

    const task_payload = {
      subTypeId: parseInt(selectedSubTypeId, 10),
      description: description || 'Tarefa criada via sistema',
      startDateTime: new Date().toISOString(),
      priority: 'Normal',
      // Você pode adicionar mais campos aqui se necessário, como responsibleOfficeId
    };

    const participants = [{
      contact_id: parseInt(selectedResponsibleId, 10),
      is_responsible: true, // Marcando este como o responsável principal
      is_executer: true,
    }];

    const requestBody = {
      cnj_number: foundLawsuit.identifierNumber,
      task_payload,
      participants,
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

                {/* Responsável */}
                <div className="space-y-2">
                  <Label htmlFor="responsible">Responsável</Label>
                  <Select value={selectedResponsibleId} onValueChange={setSelectedResponsibleId}>
                    <SelectTrigger id="responsible">
                      <SelectValue placeholder="Selecione o responsável..." />
                    </SelectTrigger>
                    <SelectContent>
                      {users.map(user => (
                        <SelectItem key={user.id} value={String(user.external_id)}>{user.name}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
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
                  <Button onClick={handleSubmit} disabled={isSubmitting || !selectedSubTypeId || !selectedResponsibleId}>
                    {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                    <span className="ml-2">Criar Tarefa</span>
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