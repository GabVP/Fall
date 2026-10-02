# Fall

Aplicação pessoal para centralizar, analisar e visualizar as finanças do usuário, incluindo contas, transações, cartões, dívidas, investimentos e patrimônio.

## Backend: estado atual

Este repositório contém a base executável da API FastAPI e do worker. Ainda não há rotas financeiras, tarefas agendadas, banco de dados ou integração com provedores. As regras de produto e os tickets permanecem fora deste repositório, no diretório pai do workspace original.

## Pré-requisitos e instalação

- Python 3.11 ou superior.
- [uv](https://docs.astral.sh/uv/getting-started/installation/) para instalar exatamente as versões registradas em `uv.lock`.

Na raiz deste repositório:

```sh
uv sync --locked
```

O comando cria `.venv/` e instala as dependências de execução e de desenvolvimento. Não é necessário configurar uma VPS para executar esta base localmente.

## Ambientes

Defina `FALL_ENVIRONMENT` antes de iniciar cada processo. Os valores aceitos são `development`, `test`, `staging` e `production`. Não existe ambiente implícito: um valor ausente ou inválido impede a inicialização. O arquivo `.env.example` mostra somente o nome da variável; a aplicação não carrega esse arquivo automaticamente.

| Perfil | Esquema e interface OpenAPI |
| --- | --- |
| `development` | Disponíveis |
| `test` | Disponíveis |
| `staging` | Desabilitados |
| `production` | Desabilitados |

Esta etapa ainda não usa credenciais, banco ou dados financeiros. A exigência e a proteção de segredos dos componentes futuros pertencem aos tickets seguintes.

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

`backend/fall/api` contém o transporte HTTP; `worker` contém o processo de trabalho; `application` receberá casos de uso; `domain` conterá regras financeiras independentes de frameworks; `integrations` e `persistence` receberão os adaptadores externos. `backend/fall/bootstrap.py` é o ponto de composição comum da API e do worker. Os próximos tickets acrescentam serviços, persistência e segurança sem duplicar regras entre processos.
