# MangaTemp: migracao para React + FastAPI + Desktop

## Arquitetura recomendada

Use Tauri + sidecar Python.

- Front-end: React + Vite + Tailwind.
- Back-end: FastAPI local rodando em `127.0.0.1`.
- Desktop: Tauri empacotando o front e iniciando o binario Python como sidecar.

Motivo: Electron empacota Chromium e Node, entao costuma consumir mais RAM. Tauri usa o WebView nativo do sistema e permite executar binarios externos como sidecar, o que encaixa bem com um back-end Python local.

## Passo a passo

1. Isolar a camada de dados
   - Extrair funcoes de busca/capitulos/capas de `reader_server.py` para servicos reutilizaveis.
   - Retornar sempre dicionarios simples e serializaveis.

2. Criar API local
   - Comecar por `backend/main.py`.
   - Rotas iniciais:
     - `GET /health`
     - `GET /api/mangas`
     - `GET /api/chapters?source_url=...`
     - depois: `GET /api/mangas/{id}`, `GET /api/chapters/{id}/pages`.
   - Estado atual: `/api/mangas` ja usa fontes reais. Sem busca, monta catalogo via MangaDex. Com busca, consulta MangaDex, MangaLivre e Toomics, filtra relevancia e preenche capas ausentes com AniList.

3. Criar front web
   - `frontend/src/App.jsx` controla busca, loading e virtualizacao.
   - `frontend/src/components/MangaCard.jsx` cuida de card, skeleton e lazy image.

4. Otimizar renderizacao
   - Virtualizar listas grandes com `react-window`.
   - Usar `loading="lazy"`, `decoding="async"` e `fetchPriority="low"` em capas.
   - Usar skeletons enquanto a API carrega.
   - Evitar setState por card; carregar dados em lote e memoizar cards.

5. Empacotar Desktop
   - Criar projeto Tauri apontando para `frontend/dist`.
   - Gerar um executavel do FastAPI com PyInstaller ou Nuitka.
   - Configurar o executavel como sidecar no Tauri.

## Comandos atuais

Back-end:

```bash
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Teste rapido:

```bash
curl "http://127.0.0.1:8000/api/mangas?q=soul%20eater&limit=8"
curl "http://127.0.0.1:8000/api/chapters?source_url=https%3A%2F%2Fmangalivre.blog%2Fmanga%2Fsoul-eater%2F"
```

Front-end:

```bash
cd frontend
npm install
npm run dev
```

Build do front:

```bash
cd frontend
npm run build
```
