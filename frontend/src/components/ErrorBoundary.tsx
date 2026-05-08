/**
 * ErrorBoundary — captura erros em runtime do React e mostra mensagem
 * legivel em vez de tela branca.
 *
 * Use envolvendo arvores de componentes que ainda estao em estabilizacao,
 * pra que um erro num componente filho nao apague a pagina inteira.
 *
 * Caso o erro persista, copiar a mensagem do componente e abrir issue.
 */
import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface Props {
  /** Conteudo a renderizar quando nao ha erro. */
  children: ReactNode;
  /** Identificacao do bloco pra log/UI (ex.: "templates-by-office"). */
  scope?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
  componentStack: string | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null, componentStack: null };
  }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Log no console pra dev abrir devtools e copiar.
    // eslint-disable-next-line no-console
    console.error("[ErrorBoundary]", this.props.scope || "root", error, info);
    this.setState({ componentStack: info.componentStack ?? null });
  }

  reset = () => {
    this.setState({ hasError: false, error: null, componentStack: null });
  };

  render() {
    if (!this.state.hasError) return this.props.children;

    return (
      <Card className="border-destructive/50">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-destructive">
            <AlertTriangle className="h-5 w-5" />
            Algo deu errado nesta seção
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <p>
            Um erro ocorreu durante a renderização. O resto da página continua
            funcionando — recarregue para tentar novamente, ou copie a mensagem
            abaixo e mande pro suporte se persistir.
          </p>
          <div className="rounded border bg-muted/50 p-3">
            <p className="font-mono text-xs break-all">
              {this.state.error?.name}: {this.state.error?.message}
            </p>
            {this.state.componentStack && (
              <details className="mt-2">
                <summary className="cursor-pointer text-xs text-muted-foreground">
                  Detalhes técnicos
                </summary>
                <pre className="mt-2 whitespace-pre-wrap text-xs text-muted-foreground">
                  {this.state.componentStack}
                </pre>
              </details>
            )}
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={this.reset}
          >
            <RefreshCw className="h-4 w-4 mr-1" />
            Tentar novamente
          </Button>
        </CardContent>
      </Card>
    );
  }
}

export default ErrorBoundary;
