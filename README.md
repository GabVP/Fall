# Fall

Aplicação pessoal para centralizar, analisar e visualizar as finanças do usuário, incluindo contas, transações, cartões, dívidas, investimentos e patrimônio.

## Backend: estado atual

Este repositório contém a base executável da API FastAPI e do worker e a configuração local do PostgreSQL. Ainda não há rotas financeiras, tarefas agendadas ou integração com provedores. As regras de produto e os tickets permanecem fora deste repositório, no diretório pai do workspace original.

## Pré-requisitos e instalação

- Python 3.11 ou superior.
- [uv](https://docs.astral.sh/uv/getting-started/installation/) para instalar exatamente as versões registradas em `uv.lock`.
- Docker com Compose para iniciar os bancos locais.

Na raiz deste repositório:

```sh
uv sync --locked
```

O comando cria `.venv/` e instala as dependências de execução e de desenvolvimento. Não é necessário configurar uma VPS para executar esta base localmente.

## Ambientes

Defina `FALL_ENVIRONMENT` antes de iniciar cada processo. Os valores aceitos são `development`, `test`, `staging` e `production`. Não existe ambiente implícito: um valor ausente ou inválido impede a inicialização. O arquivo `.env.example` mostra URLs somente para bancos locais e exemplos sem credenciais reais para outros ambientes; a aplicação não carrega esse arquivo automaticamente.

| Perfil | `/openapi.json` | `/docs` | `/redoc` |
| --- | --- | --- | --- |
| `development` | Disponível | Disponível | Disponível |
| `test` | Disponível | Disponível | Desabilitado |
| `staging` | Disponível para validação de contrato | Desabilitado | Desabilitado |
| `production` | Desabilitado | Desabilitado | Desabilitado |

As rotas e o worker ainda não usam o banco nem dados financeiros. A exigência e a proteção de segredos dos componentes futuros pertencem aos tickets seguintes.

## PostgreSQL local

O Compose fornece dois bancos distintos, acessíveis somente pelo loopback da máquina. As credenciais em `compose.yaml` servem exclusivamente para desenvolvimento e teste locais. O banco de desenvolvimento mantém um volume nomeado. A imagem PostgreSQL cria um volume anônimo para o banco de teste; para descartar seus dados sem tocar no volume de desenvolvimento, execute `docker compose --profile test rm -sfv postgres-test` e inicie o serviço novamente.

```sh
docker compose up -d --wait postgres-development
docker compose --profile test up -d --wait postgres-test
```

Defina a URL correspondente ao perfil antes de usar persistência. Em PowerShell:

```powershell
$env:FALL_ENVIRONMENT = "development"
$env:FALL_DEVELOPMENT_DATABASE_URL = "postgresql+psycopg://fall_local:fall_local_only@127.0.0.1:55432/fall_development"
```

Para teste, use `FALL_ENVIRONMENT=test` e `FALL_TEST_DATABASE_URL` apontando para `127.0.0.1:55433/fall_test`. Homologação e produção exigem, respectivamente, `FALL_STAGING_DATABASE_URL` e `FALL_PRODUCTION_DATABASE_URL` com valores providos fora do repositório. A ausência da URL do perfil selecionado ou o uso de outro dialeto causa erro sem expor o valor fornecido.

Em PowerShell:

```powershell
$env:FALL_ENVIRONMENT = "development"
```

Em shells POSIX:

```sh
export FALL_ENVIRONMENT=development
```

Para executar em outro perfil, substitua o valor antes de iniciar o processo. Use terminais separados para a API e o worker:

```sh
uv run --locked uvicorn fall.api.main:create_app --factory --host 127.0.0.1 --port 8000
uv run --locked fall-worker
```

A API de desenvolvimento expõe o esquema em `http://127.0.0.1:8000/openapi.json`. O worker permanece ativo sem tarefas registradas; encerre os processos com `Ctrl+C`.

## Testes

Selecione o perfil de teste e execute a suíte:

```powershell
$env:FALL_ENVIRONMENT = "test"
```

Ou, em shells POSIX:

```sh
export FALL_ENVIRONMENT=test
```

```sh
uv run --locked pytest
```

Os testes mínimos verificam a inicialização da API e do worker e o carregamento dos quatro perfis. Eles não dependem de conta bancária, credenciais ou PostgreSQL.

## Organização

`backend/fall/api` contém o transporte HTTP; `worker` contém o processo de trabalho; `application` receberá casos de uso; `domain` conterá regras financeiras independentes de frameworks; `integrations` e `persistence` receberão os adaptadores externos. API e worker carregam os mesmos perfis em `backend/fall/config.py`. Os próximos tickets acrescentam serviços de aplicação compartilhados, persistência e segurança sem duplicar regras entre processos.
