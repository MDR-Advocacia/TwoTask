import sys
import os
from dotenv import load_dotenv

# Adiciona o diretório atual ao path para conseguir importar 'app'
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Carrega as variáveis do arquivo .env
load_dotenv()

# Importa a função de envio
try:
    from app.services.mail_service import send_failure_report
except ImportError as e:
    print(f"❌ Erro de importação: {e}")
    print("Certifique-se de estar rodando este script da raiz do projeto.")
    sys.exit(1)

def run_test():
    print("📧 Iniciando teste de envio de e-mail...")

    # Verifica se as variáveis estão carregadas
    smtp_user = os.getenv("SMTP_USER")
    email_to_env = os.getenv("EMAIL_TO", "")
    
    # Simula a lógica de split para mostrar ao usuário quem receberá
    recipients = [email.strip() for email in email_to_env.split(',') if email.strip()]

    if not smtp_user or not recipients:
        print("❌ ERRO: Variáveis de ambiente incompletas.")
        print(f"   SMTP_USER: {smtp_user}")
        print(f"   EMAIL_TO (Bruto): {email_to_env}")
        print("Verifique seu arquivo .env e adicione e-mails separados por vírgula.")
        return

    # Cria dados falsos de falha para teste
    fake_failed_items = [
        {
            "cnj": "0000000-00.2024.8.26.0000", 
            "motivo": "Simulação de erro: Processo não encontrado no Legal One."
        },
        {
            "cnj": "TESTE-MULTIPLOS", 
            "motivo": "Verificando entrega para múltiplos destinatários."
        }
    ]

    print(f"📤 Enviando via {os.getenv('SMTP_SERVER')} para {len(recipients)} destinatário(s):")
    for mail in recipients:
        print(f"   ➡️  {mail}")
    
    try:
        # Chama a função diretamente
        send_failure_report(fake_failed_items, batch_source="TESTE MANUAL (Múltiplos E-mails)")
        print("\n✅ Função executada com sucesso!")
        print("👉 Verifique a caixa de entrada de TODOS os e-mails listados acima.")
    except Exception as e:
        print(f"\n❌ Ocorreu um erro ao enviar: {e}")

if __name__ == "__main__":
    run_test()