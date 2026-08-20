# PostCheck

Protótipo Flask para triagem de encomendas com OpenCV, Tesseract OCR, SQLite e notificação SMTP.

O dashboard responsivo inclui métricas em tempo real, captura direta pela câmera
traseira, drag-and-drop, upload pela galeria, detecção de transportadora, pesquisa
por qualquer dado da encomenda e baixa de retirada com data e hora. O acesso direto
à câmera via navegador exige HTTPS ou `localhost`; quando isso não está disponível,
o sistema abre automaticamente a captura nativa do celular.

A seção **Moradores** permite cadastrar, pesquisar, editar e excluir moradores.
Cadastros com encomendas vinculadas são preservados e não podem ser excluídos. Na
validação da etiqueta, o porteiro pode substituir ou selecionar manualmente o
morador identificado pelo OCR.

## Instalação

É necessário ter Python 3.9+ e o executável do Tesseract com o idioma português.

No macOS:

```bash
brew install tesseract tesseract-lang
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python database.py
python app.py
```

No Ubuntu/Debian, instale o OCR com `sudo apt install tesseract-ocr tesseract-ocr-por`.
Acesse `http://127.0.0.1:5001`. Para usar outra porta, defina `APP_PORT` antes
de iniciar o servidor.

## Configuração SMTP

Antes de iniciar o Flask, defina as variáveis abaixo. Sem elas, a encomenda ainda é salva e a interface informa que o e-mail não foi enviado.

```bash
export SMTP_HOST="smtp.exemplo.com"
export SMTP_PORT="587"
export SMTP_USER="usuario"
export SMTP_PASSWORD="senha"
export SMTP_FROM="portaria@exemplo.com"
export SMTP_USE_TLS="true"
```

Os três moradores de demonstração são criados automaticamente quando o banco está vazio.

## Resend sem domínio próprio (modo acadêmico)

Crie uma conta no Resend e gere uma chave em **API Keys**. Depois copie o arquivo
de exemplo e preencha somente a chave e o e-mail usado na conta Resend:

```bash
cp .env.example .env
```

```env
EMAIL_PROVIDER=resend
RESEND_API_KEY=re_sua_chave
RESEND_FROM=onboarding@resend.dev
RESEND_TEST_RECIPIENT=seu-email@gmail.com
```

O domínio de teste `resend.dev` só pode entregar mensagens ao e-mail associado à
conta Resend. Por isso, nesse modo, o sistema preserva o destinatário original no
corpo da mensagem, mas envia todas as demonstrações para `RESEND_TEST_RECIPIENT`.
Com um domínio verificado no futuro, remova `RESEND_TEST_RECIPIENT` e altere
`RESEND_FROM` para um endereço do domínio. O PostCheck usa a API HTTPS do Resend,
compatível com as restrições de rede do plano gratuito do Render.

## Publicação no Render

O repositório inclui `Dockerfile` e `render.yaml`. No Render, escolha **New →
Blueprint**, conecte o repositório e informe os dois segredos solicitados:

- `RESEND_API_KEY`: chave `re_...` gerada no Resend.
- `RESEND_TEST_RECIPIENT`: e-mail associado à conta Resend.

O Docker instala o Tesseract e o idioma português e inicia a aplicação com
Gunicorn. O endpoint `/health` é usado pelo Render para verificar o serviço.

O plano gratuito possui armazenamento efêmero: o SQLite e as imagens são
reiniciados quando o serviço hiberna, reinicia ou recebe um novo deploy. Isso é
adequado para a demonstração acadêmica, mas um uso permanente deve migrar os dados
para PostgreSQL ou usar um serviço pago com disco persistente.
