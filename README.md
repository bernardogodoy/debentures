# Debêntures estressadas

Site para acompanhar pelo celular a taxa indicativa e o PU de debêntures de emissores selecionados, com dados da ANBIMA (Mercado Secundário de Debêntures).

- **Site:** GitHub Pages deste repositório.
- **Atualização:** o workflow `Atualizar taxas ANBIMA` roda todo dia útil às 20:37 (Brasília) e de novo às 07:17 do dia seguinte. Também dá para rodar manualmente em *Actions → Atualizar taxas ANBIMA → Run workflow* (o campo "dias" faz backfill).
- **Emissores acompanhados:** edite `emissores.json` (nome + prefixo de 4 letras do código das séries). Todas as séries com aquele prefixo entram automaticamente.
- **Dados:**
  - `data/debentures.json`: foto do último dia (lista do site).
  - `data/series/CODIGO.json`: histórico completo de cada série, aberto ao tocar nela.
  - `data/historico.json`: base acumulada das taxas ANBIMA. O arquivo diário da ANBIMA só fica no ar por ~20 dias úteis, então o histórico de taxa cresce a partir da primeira coleta e nunca é apagado.
  - `data/negocios/CODIGO.json`: negócios do SND (debentures.com.br), com histórico desde a emissão. Para rebaixar tudo: *Run workflow* com "snd_completo" marcado.

Fontes: `https://www.anbima.com.br/informacoes/merc-sec-debentures/arqs/dbAAMMDD.txt` (taxas e PU indicativos) e `https://www.debentures.com.br` → Preços de Negociação (negócios registrados).
