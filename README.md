# Radar TECH history

Coleta todo dia as notícias de tecnologia e ciência de 7 sites, descobre o que está em alta
(Google Trends + quantos sites cobrem o mesmo assunto), traz o texto completo, fotos e vídeos
e deixa tudo num site que abre no celular e no PC. Custo: R$ 0.

## Como funciona

| Etapa | Ferramenta | Custo |
|---|---|---|
| Descobrir notícias dos 7 sites | RSS | grátis, 0 créditos |
| O que está em alta | Google Trends BR + cobertura entre sites | grátis |
| O que as pessoas buscam | Autocompletar do YouTube | grátis |
| Texto completo + fotos/vídeos das 8 melhores | Firecrawl | 1 crédito por notícia |
| Rodar todo dia | GitHub Actions | grátis (repositório público) |
| Site | GitHub Pages | grátis |
| Roteiro | botão copia um prompt pronto → cole no ChatGPT ou Gemini | grátis |

**Orçamento do Firecrawl:** o limite mensal (800) é dividido pelos dias que faltam no mês.
O script recalcula todo dia e nunca passa disso. Se acabar o crédito, ele continua funcionando
com extração simples e gratuita.

## Instalação (uma vez só, ~10 min)

1. Crie uma conta no GitHub e um repositório **público** (ex.: `radar-tech`). Envie todos os arquivos desta pasta.
2. Crie uma chave em firecrawl.dev e guarde: no repositório vá em
   **Settings → Secrets and variables → Actions → New repository secret**
   - Nome: `FIRECRAWL_API_KEY`  |  Valor: sua chave
3. **Settings → Pages →** Source: *Deploy from a branch* → Branch: `main` / pasta `/docs` → Save.
4. **Actions → Coleta diária → Run workflow** (primeira coleta).
5. Abra `https://SEU-USUARIO.github.io/radar-tech/` no celular e no PC.
   No celular: menu do navegador → *Adicionar à tela inicial*.

Depois disso roda sozinho todo dia às 06:00 (Brasília). Quer atualizar na hora? Rode o workflow de novo.

## Ajustes (config.json)

- `monthly_credit_limit`: coloque o que seu plano do Firecrawl realmente oferece.
- `fulltext_n`: quantas notícias por dia recebem texto completo via Firecrawl.
- `sources`: troque ou adicione sites (precisa ter feed RSS).
- `boost_keywords`: assuntos que você quer priorizar.

## Importante para monetizar

O YouTube reduz ou nega monetização de canais com conteúdo repetitivo, em massa ou
que apenas reaproveita material de terceiros. Use o texto da fonte **só como pesquisa**:
roteiro com suas palavras, sua análise e sua narração. Fotos e vídeos dos sites têm direitos
autorais; use bancos gratuitos (links em cada notícia) ou peça licença.
