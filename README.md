# Fall

Aplicação pessoal para centralizar, analisar e visualizar as finanças do usuário, incluindo contas, transações, cartões, dívidas, investimentos e patrimônio.

## Backend: estado atual

Este repositório contém a API FastAPI com login e emissão de sessão, a base executável do worker e a configuração local do PostgreSQL. Ainda não há rotas financeiras, tarefas agendadas ou integração com provedores. As regras de produto e os tickets permanecem fora deste repositório, no diretório pai do workspace original.

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

API e worker exigem o perfil para iniciar. A URL PostgreSQL correspondente é obrigatória nos comandos de migração e ao processar login. Saúde e documentação não abrem conexão ao banco. Credenciais de integrações serão exigidas nos módulos que as utilizarem.

## Contratos de acesso

`fall.api.access` expõe `POST /v1/sessions` e define os formatos de credenciais, emissão de sessão e identificação do usuário. `fall.application.access` define as portas de usuário, sessão, hash de senha e material de sessão. `fall.application.sessions.create_session` autentica o usuário ativo e cria uma sessão usando essas portas e `Clock`, sem depender do transporte ou do PostgreSQL.

Após provisionar o usuário e aplicar as migrações, envie JSON com exatamente `login` e `password`, ambos strings não vazias. O login tem até 128 caracteres, rejeita NUL e preserva maiúsculas e espaços, assim como a senha. O sucesso retorna `200`, `Cache-Control: no-store` e somente `access_token`, `token_type: "Bearer"` e `absolute_expires_at` em UTC, oito horas após o login. O servidor gera 32 bytes aleatórios em Base64URL e persiste somente o resumo SHA-256 do token, sem chave de assinatura. O token completo é entregue somente nessa resposta.

Senha incorreta, login desconhecido e usuário inativo retornam o mesmo `401 AUTHENTICATION_REQUIRED`, sem criar sessão. Entrada inválida retorna `422 VALIDATION_ERROR`; falhas de persistência ou verificação retornam `500 INTERNAL_ERROR`. Os erros usam o envelope comum e o mesmo identificador de correlação do cabeçalho `X-Request-ID`, sem credenciais ou material interno.

Este incremento cobre emissão de sessão. A validação de tokens recebidos, a expiração efetiva por 15 minutos de inatividade ou oito horas absolutas, a atualização de atividade, a revogação e as rotas `/v1/me` e de logout permanecem nos próximos blocos e tickets. O adaptador de resumo é consumido aqui somente com tokens recém-emitidos; ele ainda não deve ser usado como validador de entrada externa.

## Provisionar o usuário

Depois de instalar as dependências e aplicar a migração `0002_access`, use o mesmo `FALL_ENVIRONMENT` e a URL PostgreSQL correspondente. Em um terminal interativo, execute o comando com seu login no lugar de `usuario-exemplo`.

```sh
uv run --locked fall-provision-user --login usuario-exemplo
```

Digite a senha e confirme nos dois prompts sem eco. O comando aceita somente o login como argumento e recusa entrada redirecionada ou leitura com eco. O PostgreSQL armazena o hash Argon2id com salt. O login diferencia maiúsculas e preserva espaços.

Uma execução bem-sucedida retorna código `0`. Uma senha vazia, confirmação divergente, falha operacional ou tentativa com login já reservado ou com um usuário ativo retorna `1` e uma mensagem segura. Uso inválido do comando retorna `2`. Uma tentativa em conflito conserva o registro existente.

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

Para teste, use `FALL_ENVIRONMENT=test` e `FALL_TEST_DATABASE_URL` apontando para `127.0.0.1:55433/fall_test`. Homologação e produção exigem, respectivamente, `FALL_STAGING_DATABASE_URL` e `FALL_PRODUCTION_DATABASE_URL` com valores providos fora do repositório. Se a URL do perfil selecionado estiver ausente ou inválida, a migração informa o nome da variável. Se o driver falhar ao abrir a conexão, o comando informa a operação que falhou sem repetir o diagnóstico bruto do driver. O SQLAlchemy oculta a senha na representação padrão da URL, mas pode exibir outros campos e opções. Evite registrar a URL inteira. [Referência do SQLAlchemy](https://docs.sqlalchemy.org/en/21/core/engines.html#sqlalchemy.engine.URL.render_as_string)

## Migrações

Alembic usa o perfil em `FALL_ENVIRONMENT` e a URL correspondente. A revisão `0001_baseline` registra o histórico inicial. A revisão `0002_access` cria `users` e `sessions`. Com o banco local de desenvolvimento ativo e suas variáveis definidas:

```sh
uv run --locked alembic upgrade head
uv run --locked alembic current
```

Para conferir reversão em um banco descartável, use `uv run --locked alembic downgrade 0001_baseline` e depois `uv run --locked alembic upgrade head`. O downgrade remove os dados de `sessions` e `users` junto com suas tabelas. Os testes usam bancos temporários no servidor de teste e cobrem reversão, reaplicação, integridade e criação concorrente. Em PowerShell:

```powershell
$env:FALL_ENVIRONMENT = "test"
$env:FALL_TEST_DATABASE_URL = "postgresql+psycopg://fall_local:fall_local_only@127.0.0.1:55433/fall_test"
uv run --locked pytest tests/test_migrations.py tests/test_access_persistence.py
```

Novas revisões podem ser criadas com `uv run --locked alembic revision -m "descrição"`; o template fornece `upgrade` e `downgrade` para edição e revisão. A configuração não fornece metadados de entidades nem geração automática de tabelas neste estágio. A resolução do diretório de migrações usa a localização do `alembic.ini`.

Selecionar um ambiente escolhe sua variável de URL, mas ainda não comprova a identidade do servidor alcançado. A verificação independente de servidor, banco e papel, com bloqueio de divergências antes de migrar, está prevista no Módulo 14. A primeira migração de homologação ou produção depende dessa proteção, ainda não implementada nesta base.

## Portas e convenções de dados

`application/ports.py` define os contratos `Repository[Key, Entity]` (`get` e `save`) e `Clock` (`now`). Casos de uso recebem essas dependências; os testes demonstram a substituição por repositório em memória e relógio fixo. `save` não promete commit: a coordenação transacional será definida com os primeiros casos de uso persistentes. Repositórios de cada módulo acrescentarão operações e escopo de proprietário conforme suas entidades. `integrations/clock.py` implementa o relógio do sistema em UTC.

- Dinheiro usa `Money` com `Decimal` finito e `Currency` ISO 4217. Construa `Decimal` a partir de texto (`Decimal("0.10")`), nunca a partir de `float`; o tipo não consegue recuperar a origem de um Decimal já construído. `Money` rejeita float e valores não finitos. A lista de moedas vem de `iso4217`, com versão registrada no lockfile; atualizar essa dependência exige revisar mudanças da lista. Não há conversão cambial nem soma automática entre moedas.
- `persistence/types.py` fornece `DecimalAmount` como `NUMERIC` sem escala global, preservando os decimais enviados; `CurrencyCode` armazena o código ISO de três letras. Precisão, escala, arredondamento e limites próprios de cada recurso serão definidos nos respectivos módulos. O contexto de operações de `Decimal` deve comportar a precisão do cálculo; não foi imposta uma política global de arredondamento.
- `UTCInstant` usa `TIMESTAMP WITH TIME ZONE`, exige um datetime com fuso e normaliza escrita e leitura para UTC, inclusive se a sessão PostgreSQL usar outro fuso. PostgreSQL preserva o instante; o fuso original não é retido nessa coluna. Datas da fonte que representem somente uma data permanecem distintas de instantes de coleta.
- `as_utc` e `in_sao_paulo` exigem instantes com fuso explícito. `sao_paulo_to_utc` interpreta um horário local sem fuso em `America/Sao_Paulo`, incluindo regras históricas. Horários inexistentes no início do horário de verão são rejeitados; horários ambíguos no retorno exigem `fold=0` (primeira ocorrência) ou `fold=1` (segunda). A política do agendador ficará no módulo correspondente. `tzdata` garante disponibilidade da base IANA no Windows.

Essas convenções não criam tabelas financeiras ou de sessão. Os testes de PostgreSQL usam tabelas sintéticas somente em bancos temporários exclusivos, removidos ao terminar.

Referências: [tipos personalizados do SQLAlchemy](https://docs.sqlalchemy.org/en/20/core/custom_types.html), [moedas ISO 4217](https://pypi.org/project/iso4217/), [zoneinfo do Python](https://docs.python.org/3/library/zoneinfo.html).

## Executar API e worker

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
uv run --locked uvicorn fall.api.main:create_app --factory --no-access-log --host 127.0.0.1 --port 8000
uv run --locked fall-worker
```

A API de desenvolvimento expõe o esquema em `http://127.0.0.1:8000/openapi.json`. O worker permanece ativo sem tarefas registradas; encerre os processos com `Ctrl+C`.

`GET /health` é público nos quatro perfis e responde `200` com `{"status":"ok"}`. O resultado indica que o processo da API responde a requisições.

A API e o worker emitem logs operacionais JSON em `stderr`. Os campos comuns são `timestamp` em UTC, `level`, `component` e `event`. Eventos de inicialização incluem o nome do perfil. Mensagens de bibliotecas são representadas pelo evento `runtime_event` com seu nível. A saída omite texto livre, argumentos, cabeçalhos, URLs, corpos e tracebacks. Falhas de configuração na inicialização exibem a mensagem segura do validador.

O log de acesso do Uvicorn e a telemetria nativa do FastAPI ficam desabilitados para evitar a captura do caminho bruto, de parâmetros de consulta e de detalhes de exceções. Consulte a [configuração de logging do Uvicorn](https://uvicorn.dev/settings/#logging) e a [configuração de telemetria do FastAPI](https://fastapi.tiangolo.com/advanced/opentelemetry/#choose-what-to-record).

A API gera um identificador opaco para cada requisição HTTP e o devolve em `X-Request-ID`. Procure esse valor como `request_id` no evento `request_finished`, que registra o status HTTP quando há resposta. O worker registra o `run_id` da execução em `worker_started` e, se ela falhar, usa o mesmo ID em `worker_failed`. O contexto `worker_execution()` permite que cada tarefa abra uma execução com seu próprio ID.

## Erros HTTP

As respostas de erro da API incluem `error.code`, `error.message`, `error.request_id` e `error.retryable`. O identificador coincide com o cabeçalho `X-Request-ID`. Entradas inválidas recebem `422 VALIDATION_ERROR`. Falhas inesperadas, inclusive de validação da saída da API, recebem `500 INTERNAL_ERROR`. As mensagens são fixas e omitem o conteúdo recebido e os detalhes da exceção. [Tratamento de erros do FastAPI](https://fastapi.tiangolo.com/tutorial/handling-errors/)

`429 RATE_LIMITED` e `503 SERVICE_UNAVAILABLE` sinalizam que uma nova tentativa pode funcionar. Repetir a operação deve respeitar o cabeçalho `Retry-After`, quando presente, e as garantias de idempotência da rota. Um `500 INTERNAL_ERROR` genérico mantém `retryable` como `false`. A API preserva `WWW-Authenticate` em `401` e `Allow` em `405`.

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

Os testes de configuração, API, worker, portas e convenções de domínio rodam sem PostgreSQL. Os testes de migrações e de roundtrip dos tipos exigem o serviço `postgres-test` ativo e `FALL_TEST_DATABASE_URL` definida como no exemplo acima; sem essa variável, esses testes são marcados como ignorados. Uma URL definida com banco indisponível causa falha. O usuário do banco de teste precisa de permissão para criar e remover bancos temporários (disponível no Compose local). Nenhum teste depende de contas bancárias ou dados financeiros reais.

### Validação integrada da plataforma

1. Em uma cópia limpa, instale as dependências com `uv sync --locked`. Inicie um PostgreSQL de teste isolado e configure `FALL_ENVIRONMENT=test` e `FALL_TEST_DATABASE_URL`.
2. Em um banco descartável, execute `alembic upgrade head`, `alembic downgrade base` e `alembic upgrade head` pelo `uv run --locked`. Confirme a revisão com `uv run --locked alembic current`.
3. Inicie a API e o worker com os comandos acima. Confirme o evento `worker_started` com `run_id`, o `200` em `/health` e o `404` em `/v1/inexistente`. Compare o `request_id` desse erro com o cabeçalho `X-Request-ID` e com o evento `request_finished` da API.
4. Em um processo separado, confirme que a API e o worker recusam um perfil inválido e que o Alembic recusa a URL obrigatória ausente. Use valores sintéticos para verificar que o diagnóstico omite o valor fornecido.
5. Execute `uv run --locked pytest -rs` com o banco de teste configurado. O aceite integrado exige que os testes de PostgreSQL sejam executados.

## Organização

`backend/fall/api` contém o transporte HTTP; `worker` contém o processo de trabalho; `application` contém portas e receberá casos de uso; `domain` contém convenções monetárias e temporais independentes de frameworks; `integrations` contém o relógio do sistema; `persistence` contém a configuração PostgreSQL, os tipos e as migrações. API e worker carregam os mesmos perfis em `backend/fall/config.py`. Os próximos tickets acrescentam serviços de aplicação compartilhados, entidades e segurança sem duplicar regras entre processos.
