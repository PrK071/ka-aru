# Manga temporario

Leitor local e scraper temporario para capitulos do MangaFire, MangaDex, Toomics, DragonTea e fontes salvas como One Piece Project. Use apenas em paginas e obras que voce tem autorizacao para acessar e arquivar.

## Instalar

```powershell
python -m pip install -r requirements.txt
```

O script procura o LibreWolf automaticamente nos caminhos comuns do Windows. Se ele estiver em outro lugar, informe o caminho com `--librewolf-path`.

## Popup desktop

Use este modo quando voce nao quiser guardar os capitulos no PC. Ele abre uma janela desktop, cria uma cache temporaria no sistema, baixa as paginas sob demanda enquanto voce le e apaga a cache quando voce sai do capitulo ou fecha o app.

```powershell
python reader_app.py
```

Por padrao o app tenta usar a API MangaFire externa em `http://localhost:3000/api`. Se ela nao estiver aberta, ele cai para o fallback antigo com LibreWolf/Selenium.

Para forcar o fallback antigo:

```powershell
python reader_app.py --no-api
```

Na janela:

- `Site salvo`: `MangaDex`, `Toomics`, `One Piece Project` e `ReadFull` entram na busca automatica. `MangaFire` e `DragonTea` continuam salvos, mas sao usados quando voce cola uma URL direta deles.
- `MangaDex`: usa a API oficial `https://api.mangadex.org`, sem precisar rodar API local.
- `One Piece Project`: le a estrutura JavaScript do `https://scan.onepieceproject.com.br/`, extrai os capitulos e joga as URLs das paginas no leitor temporario.
- `ReadFull`: usa a API `readfull-server`/NovelFull para ler capitulos em texto. Se rodar a API localmente, use `--readfull-api-url`.
- `DragonTea`: aceita URL direta de capitulo e descriptografa as URLs das imagens antes de usar a cache temporaria.
- `Toomics`: busca pelo catalogo publico do Toomics e carrega episodios que a propria pagina publica entrega sem login/VIP.
- `Buscar manga por nome`: busca no site selecionado. Digite por exemplo `Soul Eater` no MangaFire ou `Chainsaw Man` no MangaDex.
- `Resultado`: escolha o manga encontrado; o app preenche a URL automaticamente.
- `Manga, slug ou URL`: ainda aceita slug/ID manual, por exemplo `soul-eaterr.2z2` no MangaFire, o UUID de uma obra no MangaDex ou uma URL de capitulo do DragonTea.
- `Capitulo`: opcional; se preencher `113`, o app seleciona esse capitulo.
- `Buscar capitulos`: carrega a lista automaticamente.
- `Abrir no leitor`: abre o capitulo escolhido em rolagem vertical, de cima para baixo.
- `Sair do capitulo e apagar cache`: remove a cache temporaria do capitulo atual.

## Leitor via navegador local

Este modo ainda existe como alternativa. Ele usa uma tela em `http://127.0.0.1:8765`.

```powershell
python reader_server.py
```

Depois abra:

```text
http://127.0.0.1:8765
```

Tambem da para ja abrir com um capitulo:

```text
http://127.0.0.1:8765/?url=https%3A%2F%2Fmangafire.to%2Fread%2Fsoul-eaterr.2z2%2Fpt-br%2Fchapter-113
```

Na tela do leitor:

- Cole a URL do manga, por exemplo `https://mangafire.to/manga/soul-eaterr.2z2`.
- `Capitulos`: busca automaticamente a lista de capitulos no idioma escolhido.
- `Capitulo`: opcional; se preencher `113`, o leitor seleciona esse capitulo na lista.
- `Abrir`: abre o capitulo selecionado. Se ainda nao buscou a lista, ele busca e abre automaticamente.
- `Anterior` e `Proximo`: mudam de capitulo quando o MangaFire retorna a lista.
- `Sair do capitulo`: apaga a cache temporaria do capitulo atual.
- `Fechar leitor`: apaga a cache e encerra o servidor local.

## API local

O `reader_server.py` tambem expoe uma API JSON em `http://127.0.0.1:8765/api/v1`. Ela usa a API MangaFire externa quando disponivel e mantem a cache temporaria local: nada fica salvo permanentemente, e `POST /api/v1/close` apaga o capitulo atual.

Para usar a API MangaFire externa, rode ela antes:

```powershell
git clone https://github.com/shafat-96/mangafire.git
cd mangafire
npm install
npm run build
npm start
```

Ela deve ficar em:

```text
http://localhost:3000/api
```

Se ela estiver em outra URL:

```powershell
python reader_app.py --api-url "http://localhost:3000/api"
python reader_server.py --api-url "http://localhost:3000/api"
```

Para testar novels com uma instancia do ReadFull:

```powershell
python reader_app.py --readfull-api-url "http://127.0.0.1:8000"
```

Buscar mangas no MangaFire:

```text
GET /api/v1/search?q=Soul%20Eater&limit=10
```

Buscar mangas no MangaDex:

```text
GET /api/v1/search?q=Chainsaw%20Man&provider=mangadex&limit=10
```

Buscar One Piece no piecePROJECT:

```text
GET /api/v1/search?q=One%20Piece&provider=pieceproject&limit=10
```

Metadados da obra, com nome, capa, status, autores, generos, idiomas e capitulos:

```text
GET /api/v1/manga?url=https%3A%2F%2Fmangafire.to%2Fmanga%2Fsoul-eaterr.2z2&lang=pt-br
```

Tambem funciona com MangaDex:

```text
GET /api/v1/manga?url=https%3A%2F%2Fmangadex.org%2Ftitle%2FUUID-DA-OBRA&lang=pt-br
```

Se quiser so os metadados da obra, sem carregar capitulos:

```text
GET /api/v1/manga?url=https%3A%2F%2Fmangafire.to%2Fmanga%2Fsoul-eaterr.2z2&chapters=0
```

Abrir um capitulo e receber a lista de paginas:

```text
GET /api/v1/chapter?url=https%3A%2F%2Fmangafire.to%2Fread%2Fsoul-eaterr.2z2%2Fpt-br%2Fchapter-113
```

Abrir um capitulo do MangaDex:

```text
GET /api/v1/chapter?url=https%3A%2F%2Fmangadex.org%2Fchapter%2FUUID-DO-CAPITULO
```

Abrir um capitulo do One Piece Project:

```text
GET /api/v1/chapter?url=pieceproject%3A%2F%2Fchapter%2F1182
```

Abrir um capitulo e ja baixar/cachear todas as paginas antes de responder:

```text
GET /api/v1/chapter?url=https%3A%2F%2Fmangafire.to%2Fread%2Fsoul-eaterr.2z2%2Fpt-br%2Fchapter-113&cache=1
```

Cada imagem vem como URL local, por exemplo:

```text
GET /api/v1/image/1
```

Apagar cache do capitulo atual:

```text
POST /api/v1/close
```

## Baixar permanente

Use este modo so quando quiser salvar os arquivos em `downloads/`.

## Testar um capitulo antes de salvar

Primeiro rode em modo teste para confirmar quantas imagens seriam baixadas:

```powershell
python mangafire_scraper.py "https://mangafire.to/read/soul-eaterr.2z2/pt-br/chapter-113" --dry-run
```

Depois baixe:

```powershell
python mangafire_scraper.py "https://mangafire.to/read/soul-eaterr.2z2/pt-br/chapter-113"
```

As imagens ficam em:

```text
downloads/<nome-do-manga>/chapter-113/
```

## Baixar por numero do capitulo

Tambem da para passar a pagina do manga e escolher o capitulo:

```powershell
python mangafire_scraper.py "https://mangafire.to/manga/soul-eaterr.2z2" --lang pt-br --only-chapter 113
```

Ou baixar uma faixa:

```powershell
python mangafire_scraper.py "https://mangafire.to/read/soul-eaterr.2z2/pt-br/chapter-113" --from-chapter 110 --to-chapter 113
```

## Se o site bloquear headless

Mostre a janela do navegador:

```powershell
python mangafire_scraper.py "https://mangafire.to/read/soul-eaterr.2z2/pt-br/chapter-113" --show-browser
```

Se o LibreWolf nao for encontrado:

```powershell
python mangafire_scraper.py "https://mangafire.to/read/soul-eaterr.2z2/pt-br/chapter-113" --librewolf-path "C:\Program Files\LibreWolf\librewolf.exe"
```

## Scraper generico

`image_scraper.py` continua disponivel para outros sites quando voce souber o seletor CSS do container de imagens.

## DragonTea

O leitor tambem reconhece URL direta de capitulo do `dragontea.ink`. Cole a URL no campo `Manga, slug ou URL` e clique em `Abrir no leitor`. O servidor usa Playwright so para executar a descriptografia que a pagina ja carrega, coleta as URLs reais e depois baixa as paginas pela cache temporaria normal.

Pelo servidor local tambem funciona assim:

```text
http://127.0.0.1:8765/?url=https%3A%2F%2Fdragontea.ink%2FURL-DO-CAPITULO
```

Se a pagina bloquear navegador invisivel:

```powershell
python reader_app.py --show-browser
python reader_server.py --show-browser
```

Por padrao o DragonTea tenta usar o Microsoft Edge instalado no Windows. Se quiser usar o Chromium do Playwright:

```powershell
python -m playwright install chromium
python reader_app.py --dragontea-browser chromium
```
