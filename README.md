# Debêntures estressadas

Site para acompanhar pelo celular a taxa indicativa e o PU de debêntures de emissores selecionados, com dados da ANBIMA (Mercado Secundário de Debêntures).

- **Site:** GitHub Pages deste repositório.
- **Atualização:** o workflow `Atualizar taxas ANBIMA` roda todo dia útil às 20:37 (Brasília) e de novo às 07:17 do dia seguinte. Também dá para rodar manualmente em *Actions → Atualizar taxas ANBIMA → Run workflow* (o campo "dias" faz backfill).
- **Emissores acompanhados:** edite `emissores.json` (nome + prefixo de 4 letras do código das séries). Todas as séries com aquele prefixo entram automaticamente.
- **Dados:** `data/debentures.json` (foto do último dia, usado pelo site) e `data/historico.json` (até 90 pregões).

Fonte: `https://www.anbima.com.br/informacoes/merc-sec-debentures/arqs/dbAAMMDD.txt`.
