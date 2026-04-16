// frontend/src/pages/AdminPage.tsx

import { useState, useEffect } from 'react';
import { useToast } from "@/hooks/use-toast";
import { useAuth } from "@/hooks/useAuth";
import { useQuery, useMutation } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Loader2, Save, Pencil, RefreshCw, AlertCircle, Copy, Shield } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogClose } from "@/components/ui/dialog";
import { MultiSelect } from "@/components/ui/MultiSelect";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { apiFetch } from "@/lib/api-client";

// --- Tipos de Dados ---
interface Sector { id: number; name: string; }
interface Squad { id: number; name: string; }
interface TaskTypeGroup { parent_id: number; parent_name: string; sub_types: { id: number; name: string; squad_ids: number[]; }[]; }
interface AdminUser {
  id: number;
  name: string;
  email: string;
  external_id: number;
  is_active: boolean;
  role: string;
  can_schedule_batch: boolean;
  can_use_publications: boolean;
  default_office_id: number | null;
  has_password: boolean;
  must_change_password: boolean;
}
interface Office {
  id: number;
  name: string;
}

// --- Componente de Associação (Código completo restaurado) ---
const AssociateTasks = () => {
    const { toast } = useToast();
    const [taskGroups, setTaskGroups] = useState<TaskTypeGroup[]>([]);
    const [sectors, setSectors] = useState<Sector[]>([]);
    const [squads, setSquads] = useState<Squad[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);
    const [selectedSector, setSelectedSector] = useState<string | null>(null);
    const [isEditDialogOpen, setIsEditDialogOpen] = useState(false);
    const [editingGroup, setEditingGroup] = useState<{ id: number; name: string } | null>(null);
    const [newGroupName, setNewGroupName] = useState("");
    const [selectedSquads, setSelectedSquads] = useState<Record<number, string[]>>({});

    const fetchInitialData = async () => {
        setLoading(true);
        setError(null);
        try {
            const [tasksResponse, sectorsResponse] = await Promise.all([
                apiFetch('/api/v1/admin/task-types'),
                apiFetch('/api/v1/sectors'),
            ]);
            if (!tasksResponse.ok || !sectorsResponse.ok) throw new Error('Falha ao carregar dados iniciais.');
            
            const tasksData = await tasksResponse.json();
            const sectorsData = await sectorsResponse.json();
            setTaskGroups(tasksData);
            setSectors(sectorsData);
            setSquads([]);

            const initialSelectedSquads: Record<number, string[]> = {};
            tasksData.forEach((group: TaskTypeGroup) => {
                const squadIdsInGroup = new Set<string>();
                group.sub_types.forEach(st => {
                    if (st.squad_ids) st.squad_ids.forEach(id => squadIdsInGroup.add(String(id)));
                });
                initialSelectedSquads[group.parent_id] = Array.from(squadIdsInGroup);
            });
            setSelectedSquads(initialSelectedSquads);
        } catch (err: any) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    };

    const fetchSquadsBySector = async (sectorId: string) => {
        try {
            const res = await apiFetch(`/api/v1/squads?sector_id=${sectorId}`);
            if (!res.ok) throw new Error('Falha ao buscar squads.');
            setSquads(await res.json());
        } catch (err: any) {
            toast({ title: "Erro ao Carregar Squads", description: err.message, variant: "destructive" });
        }
    };

    useEffect(() => { fetchInitialData(); }, []);
    useEffect(() => {
        if (selectedSector) {
            fetchSquadsBySector(selectedSector);
        } else {
            setSquads([]);
        }
    }, [selectedSector]);

    const handleEditClick = (group: { parent_id: number; parent_name: string }) => {
        setEditingGroup({ id: group.parent_id, name: group.parent_name });
        setNewGroupName(group.parent_name);
        setIsEditDialogOpen(true);
    };

    const handleRenameSave = async () => {
        if (!editingGroup || !newGroupName.trim()) return;
        try {
            const res = await apiFetch(`/api/v1/admin/task-parent-groups/${editingGroup.id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: newGroupName.trim() }),
            });
            if (!res.ok) throw new Error((await res.json()).detail || "Falha ao renomear.");
            toast({ title: "Sucesso!", description: "Grupo renomeado." });
            setIsEditDialogOpen(false);
            fetchInitialData();
        } catch (err: any) {
            toast({ title: "Erro ao Renomear", description: err.message, variant: "destructive" });
        }
    };

    const handleSaveChanges = async (groupId: number) => {
        const squadIds = selectedSquads[groupId] || [];
        const group = taskGroups.find(g => g.parent_id === groupId);
        if (!group) return;
        setSaving(true);
        try {
            const res = await apiFetch('/api/v1/admin/task-types/associate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    squad_ids: squadIds.map(id => parseInt(id, 10)),
                    task_type_ids: group.sub_types.map(st => st.id),
                }),
            });
            if (!res.ok) throw new Error((await res.json()).detail || "Falha ao salvar.");
            toast({ title: "Sucesso!", description: "Associações salvas." });
            fetchInitialData();
        } catch (err: any) {
            toast({ title: "Erro ao Salvar", description: err.message, variant: "destructive" });
        } finally {
            setSaving(false);
        }
    };

    if (loading) return <div className="flex items-center justify-center h-64"><Loader2 className="h-8 w-8 animate-spin" /></div>;
    if (error) return <Alert variant="destructive"><AlertCircle className="h-4 w-4 mr-2" /><AlertTitle>Erro</AlertTitle><AlertDescription>{error}</AlertDescription></Alert>;

    return (
        <Card>
            <CardHeader>
                <CardTitle>Associação de Tipos de Tarefa a Squads</CardTitle>
                <CardDescription>Filtre por setor, depois associe grupos de tarefas a um ou mais squads.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
                <div className="w-full md:w-1/3">
                    <Label htmlFor="sector-select">1. Selecione um Setor</Label>
                    <Select onValueChange={setSelectedSector} value={selectedSector || ""}><SelectTrigger><SelectValue placeholder="Escolha um setor..." /></SelectTrigger><SelectContent>{sectors.map(s => <SelectItem key={s.id} value={String(s.id)}>{s.name}</SelectItem>)}</SelectContent></Select>
                </div>
                <div className="border-t pt-6">
                    <h3 className="text-lg font-medium mb-4">2. Associe os Grupos de Tarefas</h3>
                    <p className="text-sm text-muted-foreground mb-4">
                        Cada grupo de tarefas abaixo pode ser associado a um ou mais squads do setor selecionado. As associações são salvas por grupo.
                    </p>
                    <Accordion type="single" collapsible className="w-full">
                        {taskGroups.map(group => (
                            <AccordionItem value={`item-${group.parent_id}`} key={group.parent_id}>
                                <AccordionTrigger>
                                    <span className="flex-grow text-left">{group.parent_name}</span>
                                    <Button variant="ghost" size="icon" className="ml-4 h-8 w-8" onClick={(e) => { e.stopPropagation(); handleEditClick(group); }}><Pencil className="h-4 w-4" /></Button>
                                </AccordionTrigger>
                                <AccordionContent>
                                    <div className="space-y-4 p-2">
                                        <div className="flex flex-col md:flex-row items-start md:items-center gap-4 p-4 border rounded-lg">
                                            <div className="flex-grow w-full">
                                                <Label className={!selectedSector ? "text-muted-foreground" : ""}>Associar grupo aos Squads:</Label>
                                                <MultiSelect
                                                    options={squads.map(s => ({ label: s.name, value: String(s.id) }))}
                                                    defaultValue={selectedSquads[group.parent_id] || []}
                                                    onValueChange={(v) => setSelectedSquads(p => ({ ...p, [group.parent_id]: v }))}
                                                    placeholder={!selectedSector ? "Selecione um setor para carregar squads" : "Selecione squads..."}
                                                    disabled={!selectedSector || squads.length === 0}
                                                />
                                            </div>
                                            <Button onClick={() => handleSaveChanges(group.parent_id)} disabled={saving || !selectedSector}>
                                                <Save className="mr-2 h-4 w-4" />
                                                {saving ? "Salvando..." : "Salvar"}
                                            </Button>
                                        </div>
                                    </div>
                                </AccordionContent>
                            </AccordionItem>
                        ))}
                    </Accordion>
                </div>
            </CardContent>
            <Dialog open={isEditDialogOpen} onOpenChange={setIsEditDialogOpen}><DialogContent><DialogHeader><DialogTitle>Renomear Grupo</DialogTitle></DialogHeader><div className="py-4"><Label htmlFor="group-name">Novo nome para "{editingGroup?.name}"</Label><Input id="group-name" value={newGroupName} onChange={(e) => setNewGroupName(e.target.value)} className="mt-2" autoFocus /></div><DialogFooter><DialogClose asChild><Button type="button" variant="secondary">Cancelar</Button></DialogClose><Button type="button" onClick={handleRenameSave}>Salvar</Button></DialogFooter></DialogContent></Dialog>
        </Card>
    );
};

// --- Componente para Sincronização ---
const SyncManager = () => {
    const { toast } = useToast();
    const [isSyncing, setIsSyncing] = useState(false);
    const [isCacheWarming, setIsCacheWarming] = useState(false);

    const handleSync = async () => {
        setIsSyncing(true);
        toast({
            title: "Sincronização Iniciada",
            description: "O processo foi iniciado em segundo plano e pode levar alguns minutos.",
        });

        try {
            const response = await apiFetch('/api/v1/admin/sync-metadata', {
                method: 'POST',
            });

            if (response.status !== 202) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Falha ao disparar a sincronização.');
            }
        } catch (error: any) {
            toast({
                title: "Erro ao Iniciar Sincronização",
                description: error.message,
                variant: "destructive",
            });
        } finally {
            setTimeout(() => {
                setIsSyncing(false);
                toast({
                    title: "Ação Enviada",
                    description: "Verifique os logs do servidor para acompanhar o progresso da sincronização.",
                });
            }, 3000);
        }
    };

    const handleCacheWarm = async () => {
        setIsCacheWarming(true);
        toast({
            title: "Pré-carga de Caches Iniciada",
            description: "Carregando índices de escritórios e dados de processos em segundo plano...",
        });

        try {
            const response = await apiFetch('/api/v1/admin/sync-caches', {
                method: 'POST',
            });

            if (response.status !== 202) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Falha ao disparar a pré-carga de caches.');
            }
            const data = await response.json();
            toast({
                title: "Pré-carga Disparada",
                description: `Carregando caches para ${data.offices || '?'} escritórios. Isso pode levar alguns minutos.`,
            });
        } catch (error: any) {
            toast({
                title: "Erro ao Iniciar Pré-carga",
                description: error.message,
                variant: "destructive",
            });
        } finally {
            setTimeout(() => setIsCacheWarming(false), 5000);
        }
    };

    return (
        <div className="space-y-4">
            <Card>
                <CardHeader>
                    <CardTitle>Sincronização de Metadados</CardTitle>
                    <CardDescription>
                        Mantenha os dados do sistema (escritórios, usuários, tipos de tarefas) atualizados com o Legal One.
                    </CardDescription>
                </CardHeader>
                <CardContent>
                    <Button onClick={handleSync} disabled={isSyncing}>
                        {isSyncing ? (
                            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        ) : (
                            <RefreshCw className="mr-2 h-4 w-4" />
                        )}
                        {isSyncing ? "Sincronizando..." : "Iniciar Sincronização Manual"}
                    </Button>
                </CardContent>
            </Card>

            <Card>
                <CardHeader>
                    <CardTitle>Cache de Escritórios e Processos</CardTitle>
                    <CardDescription>
                        Pré-carrega o índice de processos por escritório e os dados dos processos (CNJ, data de criação da pasta).
                        Acelera a primeira busca de publicações e economiza chamadas à API do Legal One.
                    </CardDescription>
                </CardHeader>
                <CardContent>
                    <Button onClick={handleCacheWarm} disabled={isCacheWarming} variant="outline">
                        {isCacheWarming ? (
                            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        ) : (
                            <RefreshCw className="mr-2 h-4 w-4" />
                        )}
                        {isCacheWarming ? "Carregando caches..." : "Pré-carregar Caches"}
                    </Button>
                </CardContent>
            </Card>
        </div>
    )
}

// --- Componente de Usuários & Permissões ---
const UsersAndPermissions = () => {
    const { toast } = useToast();
    const [editingUserId, setEditingUserId] = useState<number | null>(null);
    const [editingData, setEditingData] = useState<Partial<AdminUser>>({});
    const [tempPasswordDialog, setTempPasswordDialog] = useState<{ isOpen: boolean; password?: string; userName?: string }>({ isOpen: false });
    const [searchQuery, setSearchQuery] = useState('');

    const { data: users = [], isLoading: usersLoading, refetch: refetchUsers } = useQuery({
        queryKey: ['admin-users'],
        queryFn: async () => {
            const res = await apiFetch('/api/v1/admin/users');
            if (!res.ok) throw new Error('Falha ao carregar usuários');
            return res.json() as Promise<AdminUser[]>;
        },
    });

    const { data: offices = [], isLoading: officesLoading } = useQuery({
        queryKey: ['offices'],
        queryFn: async () => {
            const res = await apiFetch('/api/v1/offices');
            if (!res.ok) throw new Error('Falha ao carregar escritórios');
            return res.json() as Promise<Office[]>;
        },
    });

    const updateUserMutation = useMutation({
        mutationFn: async (data: { userId: number; updates: Partial<AdminUser> }) => {
            const res = await apiFetch(`/api/v1/admin/users/${data.userId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data.updates),
            });
            if (!res.ok) throw new Error('Falha ao atualizar usuário');
            return res.json();
        },
        onSuccess: () => {
            toast({ title: 'Sucesso', description: 'Usuário atualizado.' });
            setEditingUserId(null);
            refetchUsers();
        },
        onError: (err: any) => {
            toast({ title: 'Erro', description: err.message, variant: 'destructive' });
        },
    });

    const activateUserMutation = useMutation({
        mutationFn: async (userId: number) => {
            const res = await apiFetch(`/api/v1/admin/users/${userId}/activate`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
            });
            if (!res.ok) throw new Error('Falha ao ativar usuário');
            return res.json();
        },
        onSuccess: (data) => {
            setTempPasswordDialog({ isOpen: true, password: data.temp_password, userName: data.name });
            refetchUsers();
        },
        onError: (err: any) => {
            toast({ title: 'Erro', description: err.message, variant: 'destructive' });
        },
    });

    const resetPasswordMutation = useMutation({
        mutationFn: async (userId: number) => {
            const res = await apiFetch(`/api/v1/admin/users/${userId}/reset-password`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
            });
            if (!res.ok) throw new Error('Falha ao resetar senha');
            return res.json();
        },
        onSuccess: (data) => {
            setTempPasswordDialog({ isOpen: true, password: data.temp_password, userName: data.name });
            refetchUsers();
        },
        onError: (err: any) => {
            toast({ title: 'Erro', description: err.message, variant: 'destructive' });
        },
    });

    const deactivateUserMutation = useMutation({
        mutationFn: async (userId: number) => {
            const res = await apiFetch(`/api/v1/admin/users/${userId}/deactivate`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
            });
            if (!res.ok) throw new Error('Falha ao desativar usuário');
            return res.json();
        },
        onSuccess: () => {
            toast({ title: 'Sucesso', description: 'Usuário desativado.' });
            refetchUsers();
        },
        onError: (err: any) => {
            toast({ title: 'Erro', description: err.message, variant: 'destructive' });
        },
    });

    const handleEditClick = (user: AdminUser) => {
        setEditingUserId(user.id);
        setEditingData({ ...user });
    };

    const handleSave = (userId: number) => {
        updateUserMutation.mutate({ userId, updates: editingData });
    };

    const filteredUsers = users.filter(u =>
        u.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        u.email.toLowerCase().includes(searchQuery.toLowerCase())
    );

    const getOfficeName = (id: number | null) => {
        if (!id) return '—';
        return offices.find(o => o.id === id)?.name || 'Desconhecido';
    };

    const copyToClipboard = (text: string) => {
        navigator.clipboard.writeText(text);
        toast({ title: 'Copiado!', description: 'Senha copiada para a área de transferência.' });
    };

    if (usersLoading || officesLoading) return <Loader2 className="h-8 w-8 animate-spin" />;

    return (
        <Card>
            <CardHeader>
                <CardTitle>Usuários & Permissões</CardTitle>
                <CardDescription>Gerencie papéis, permissões e acesso dos usuários.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
                <Input
                    placeholder="Buscar por nome ou e-mail..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="w-full"
                />
                <div className="overflow-x-auto">
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead>Nome</TableHead>
                                <TableHead>E-mail</TableHead>
                                <TableHead>Status</TableHead>
                                <TableHead>Acesso</TableHead>
                                <TableHead>Papel</TableHead>
                                <TableHead>Agendar</TableHead>
                                <TableHead>Publicações</TableHead>
                                <TableHead>Escritório</TableHead>
                                <TableHead>Ações</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {filteredUsers.map((user) => (
                                <TableRow key={user.id}>
                                    <TableCell className="font-medium text-sm">{user.name}</TableCell>
                                    <TableCell className="font-mono text-sm">{user.email}</TableCell>
                                    <TableCell>
                                        <Badge variant={user.is_active ? "default" : "secondary"}>
                                            {user.is_active ? "Ativo" : "Inativo"}
                                        </Badge>
                                    </TableCell>
                                    <TableCell>
                                        <Badge variant={user.has_password ? "outline" : "destructive"}>
                                            {user.has_password ? "Configurado" : "Sem senha"}
                                        </Badge>
                                    </TableCell>
                                    <TableCell>
                                        {editingUserId === user.id ? (
                                            <Select value={editingData.role || ''} onValueChange={(v) => setEditingData({ ...editingData, role: v })}>
                                                <SelectTrigger className="w-24"><SelectValue /></SelectTrigger>
                                                <SelectContent>
                                                    <SelectItem value="admin">Admin</SelectItem>
                                                    <SelectItem value="user">User</SelectItem>
                                                </SelectContent>
                                            </Select>
                                        ) : (
                                            <span className="text-sm">{user.role}</span>
                                        )}
                                    </TableCell>
                                    <TableCell>
                                        {editingUserId === user.id ? (
                                            <Checkbox
                                                checked={editingData.can_schedule_batch ?? false}
                                                onCheckedChange={(c) => setEditingData({ ...editingData, can_schedule_batch: !!c })}
                                            />
                                        ) : (
                                            <Checkbox checked={user.can_schedule_batch} disabled />
                                        )}
                                    </TableCell>
                                    <TableCell>
                                        {editingUserId === user.id ? (
                                            <Checkbox
                                                checked={editingData.can_use_publications ?? false}
                                                onCheckedChange={(c) => setEditingData({ ...editingData, can_use_publications: !!c })}
                                            />
                                        ) : (
                                            <Checkbox checked={user.can_use_publications} disabled />
                                        )}
                                    </TableCell>
                                    <TableCell>
                                        {editingUserId === user.id ? (
                                            <Select value={editingData.default_office_id ? String(editingData.default_office_id) : '__none__'} onValueChange={(v) => setEditingData({ ...editingData, default_office_id: v === '__none__' ? null : parseInt(v) })}>
                                                <SelectTrigger className="w-32"><SelectValue /></SelectTrigger>
                                                <SelectContent>
                                                    <SelectItem value="__none__">Nenhum</SelectItem>
                                                    {offices.map((o) => (
                                                        <SelectItem key={o.id} value={String(o.id)}>{o.name}</SelectItem>
                                                    ))}
                                                </SelectContent>
                                            </Select>
                                        ) : (
                                            <span className="text-sm">{getOfficeName(user.default_office_id)}</span>
                                        )}
                                    </TableCell>
                                    <TableCell className="space-y-1">
                                        {editingUserId === user.id ? (
                                            <div className="flex gap-1">
                                                <Button
                                                    size="sm"
                                                    variant="default"
                                                    onClick={() => handleSave(user.id)}
                                                    disabled={updateUserMutation.isPending}
                                                >
                                                    <Save className="h-3 w-3" />
                                                </Button>
                                                <Button
                                                    size="sm"
                                                    variant="secondary"
                                                    onClick={() => setEditingUserId(null)}
                                                >
                                                    ✕
                                                </Button>
                                            </div>
                                        ) : (
                                            <div className="flex flex-col gap-1">
                                                {!user.has_password && (
                                                    <Button
                                                        size="sm"
                                                        variant="default"
                                                        onClick={() => activateUserMutation.mutate(user.id)}
                                                        disabled={activateUserMutation.isPending}
                                                    >
                                                        <Shield className="h-3 w-3 mr-1" />
                                                        Ativar
                                                    </Button>
                                                )}
                                                {user.has_password && (
                                                    <Button
                                                        size="sm"
                                                        variant="outline"
                                                        onClick={() => resetPasswordMutation.mutate(user.id)}
                                                        disabled={resetPasswordMutation.isPending}
                                                    >
                                                        Resetar
                                                    </Button>
                                                )}
                                                <Button
                                                    size="sm"
                                                    variant="outline"
                                                    onClick={() => handleEditClick(user)}
                                                >
                                                    <Pencil className="h-3 w-3" />
                                                </Button>
                                                <Button
                                                    size="sm"
                                                    variant={user.is_active ? "outline" : "default"}
                                                    onClick={() => user.is_active ? deactivateUserMutation.mutate(user.id) : null}
                                                    disabled={deactivateUserMutation.isPending || !user.is_active}
                                                >
                                                    {user.is_active ? "Desativar" : "Inativo"}
                                                </Button>
                                            </div>
                                        )}
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                </div>
            </CardContent>

            <Dialog open={tempPasswordDialog.isOpen} onOpenChange={(open) => setTempPasswordDialog({ isOpen: open })}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>Senha Gerada para {tempPasswordDialog.userName}</DialogTitle>
                    </DialogHeader>
                    <Alert className="bg-blue-50 border-blue-200">
                        <AlertCircle className="h-4 w-4 text-blue-600" />
                        <AlertDescription className="text-blue-800">
                            Esta senha só será exibida uma vez. Copie-a com segurança e repasse ao usuário.
                        </AlertDescription>
                    </Alert>
                    <div className="flex gap-2 items-center bg-muted p-3 rounded font-mono text-sm">
                        <span className="flex-1 break-all">{tempPasswordDialog.password}</span>
                        <Button
                            size="sm"
                            variant="outline"
                            onClick={() => copyToClipboard(tempPasswordDialog.password || '')}
                        >
                            <Copy className="h-4 w-4" />
                        </Button>
                    </div>
                    <DialogFooter>
                        <Button onClick={() => setTempPasswordDialog({ isOpen: false })}>Fechar</Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </Card>
    );
};

// --- Componente Principal da Página (Renderizando todos) ---
const AdminPage = () => {
    const { isAdmin } = useAuth();

    if (!isAdmin) {
        return (
            <div className="container mx-auto px-6 py-8">
                <Alert variant="destructive">
                    <AlertCircle className="h-4 w-4" />
                    <AlertTitle>Acesso Negado</AlertTitle>
                    <AlertDescription>Você não tem permissão para acessar esta página.</AlertDescription>
                </Alert>
            </div>
        );
    }

    return (
        <div className="container mx-auto px-6 py-8 space-y-8">
            <div className="mb-8">
                <h1 className="text-3xl font-bold">Painel Administrativo</h1>
                <p className="text-muted-foreground mt-1">
                    Gerencie as configurações e associações do sistema.
                </p>
            </div>

            <Tabs defaultValue="sync" className="w-full">
                <TabsList>
                    <TabsTrigger value="sync">Sincronização</TabsTrigger>
                    <TabsTrigger value="tasks">Tipos de Tarefa</TabsTrigger>
                    <TabsTrigger value="users">Usuários & Permissões</TabsTrigger>
                </TabsList>
                <TabsContent value="sync" className="space-y-6">
                    <SyncManager />
                </TabsContent>
                <TabsContent value="tasks" className="space-y-6">
                    <AssociateTasks />
                </TabsContent>
                <TabsContent value="users" className="space-y-6">
                    <UsersAndPermissions />
                </TabsContent>
            </Tabs>
        </div>
    )
}

export default AdminPage;
