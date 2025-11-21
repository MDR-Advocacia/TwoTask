import smtplib
import os
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

def send_failure_report(failed_items: list, batch_source: str = "OneRequest"):
    """
    Envia um e-mail relatando as falhas no processamento em lote.
    Suporta múltiplos destinatários separados por vírgula na variável EMAIL_TO.
    """
    # Carrega configurações do ambiente
    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = int(os.getenv("SMTP_PORT", 587))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    email_from = os.getenv("EMAIL_FROM")
    
    # Processamento de múltiplos e-mails
    email_to_env = os.getenv("EMAIL_TO", "")
    # Divide por vírgula e remove espaços em branco extras
    recipients = [email.strip() for email in email_to_env.split(',') if email.strip()]

    # Valida configurações básicas
    if not all([smtp_server, smtp_user, smtp_password, recipients]):
        logging.warning("Configurações de SMTP incompletas ou nenhum destinatário definido. E-mail não enviado.")
        return

    # Junta os e-mails para o cabeçalho visual (ex: "a@a.com, b@b.com")
    email_to_header = ", ".join(recipients)

    subject = f"⚠️ Alerta de Falha: Processamento {batch_source} - {datetime.now().strftime('%d/%m/%Y %H:%M')}"

    # Monta o corpo do e-mail em HTML
    html_content = f"""
    <html>
    <body>
        <h2 style="color: #d9534f;">Relatório de Falhas no Processamento</h2>
        <p>O sistema encontrou erros ao processar o lote via <strong>{batch_source}</strong>.</p>
        <p><strong>Total de falhas:</strong> {len(failed_items)}</p>
        
        <table border="1" cellpadding="5" cellspacing="0" style="border-collapse: collapse; width: 100%; border-color: #ddd;">
            <thead>
                <tr style="background-color: #f2f2f2;">
                    <th style="text-align: left;">CNJ / Identificador</th>
                    <th style="text-align: left;">Motivo do Erro</th>
                </tr>
            </thead>
            <tbody>
    """

    for item in failed_items:
        cnj = item.get('cnj', 'N/A')
        motivo = item.get('motivo', 'Erro desconhecido')
        html_content += f"""
                <tr>
                    <td>{cnj}</td>
                    <td style="color: #d9534f;">{motivo}</td>
                </tr>
        """

    html_content += """
            </tbody>
        </table>
        <br>
        <p style="font-size: 12px; color: #666;">Este é um e-mail automático do sistema TwoTask.</p>
    </body>
    </html>
    """

    try:
        msg = MIMEMultipart()
        msg['From'] = email_from or smtp_user
        msg['To'] = email_to_header # Cabeçalho visível no e-mail
        msg['Subject'] = subject
        msg.attach(MIMEText(html_content, 'html'))

        # Conexão com o servidor SMTP
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls() # Segurança TLS
            server.login(smtp_user, smtp_password)
            # sendmail aceita uma LISTA de strings para o envelope de envio
            server.sendmail(msg['From'], recipients, msg.as_string())
            
        logging.info(f"E-mail de alerta de falhas enviado com sucesso para: {email_to_header}")

    except Exception as e:
        logging.error(f"Erro crítico ao tentar enviar e-mail de alerta: {e}")