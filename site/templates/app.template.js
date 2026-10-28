// Gerado por scripts/build_site.py a partir de relatorios/fiscalizacao/varredura/resumo_por_eleicao.csv. Não editar à mão.
const records = __RECORDS__;
const fmt = new Intl.NumberFormat('pt-BR');
const pct = (a, b, d = 1) => b ? (100 * a / b).toLocaleString('pt-BR', { maximumFractionDigits: d, minimumFractionDigits: d }) + '%' : '—';
const selection = document.querySelector('#eleicao');
function update() {
  const r = records[selection.value];
  document.querySelector('#chart-title').textContent = selection.selectedOptions[0].textContent;
  document.querySelector('#total').textContent = fmt.format(r.secoes);
  document.querySelector('#signal').textContent = fmt.format(r.com_comportamento);
  document.querySelector('#fraction').textContent = pct(r.com_comportamento, r.secoes);
  document.querySelector('#late-number').textContent = fmt.format(r.tardia);
  document.querySelector('#manual-number').textContent = fmt.format(r.manual);
  const max = Math.max(r.tardia, r.manual);
  document.querySelector('#late-bar').style.width = (r.tardia / max * 100) + '%';
  document.querySelector('#manual-bar').style.width = (r.manual / max * 100) + '%';
  document.querySelector('#local-n').textContent = fmt.format(r.local_com_comportamento);
  document.querySelector('#local-pct').textContent = pct(r.local_dif_real, r.local_com_comportamento);
  document.querySelector('#local-base').textContent = pct(r.local_comuns_real, r.local_comuns);
  document.querySelector('#local-a').textContent = r.local_dif_real ? pct(r.local_favor_A, r.local_dif_real, 0) : '—';
  document.querySelector('#local-a-base').textContent = r.local_comuns_real ? pct(r.local_comuns_favor_A, r.local_comuns_real, 0) : '—';
  document.querySelector('#municipio-n').textContent = fmt.format(r.cmp_municipio);
}
selection.addEventListener('change', update);
update();
const dialog = document.querySelector('#apoio');
document.querySelectorAll('[data-support]').forEach(b => b.addEventListener('click', () => dialog.showModal()));
document.querySelector('.close').addEventListener('click', () => dialog.close());
dialog.addEventListener('click', e => { if (e.target === dialog) { const r = dialog.getBoundingClientRect(); if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) dialog.close(); } });
document.querySelector('#copy-pix').addEventListener('click', async () => {
  const key = '__PIX__';
  try { await navigator.clipboard.writeText(key); document.querySelector('#copy-status').textContent = 'Chave Pix copiada. Confira o destinatário no aplicativo do seu banco.'; }
  catch { document.querySelector('#copy-status').textContent = 'Chave Pix: ' + key; }
});
const homeBtn = document.querySelector('#copy-pix-home');
if (homeBtn) homeBtn.addEventListener('click', async () => {
  const key = '__PIX__';
  try { await navigator.clipboard.writeText(key); document.querySelector('#copy-status-home').textContent = 'Chave Pix copiada. Confira o destinatário no aplicativo do seu banco.'; }
  catch { document.querySelector('#copy-status-home').textContent = 'Chave Pix: ' + key; }
});
// galeria: ampliação por botão (teclado e leitor de tela), com título e legenda no diálogo
document.querySelectorAll('.gallery .zoom-btn').forEach(b => b.addEventListener('click', () => {
  const fig = b.closest('figure'), d = document.querySelector('#zoom'), img = fig.querySelector('img');
  d.querySelector('img').src = img.src; d.querySelector('img').alt = img.alt;
  d.querySelector('#zoom-titulo').textContent = fig.querySelector('figcaption b').textContent;
  d.querySelector('#zoom-legenda').textContent = ' ' + fig.querySelector('figcaption').textContent.replace(fig.querySelector('figcaption b').textContent, '').replace(/Ver no caderno.*$/, '').trim();
  d.showModal(); d.querySelector('.close').focus();
}));
document.querySelector('#zoom .close').addEventListener('click', () => document.querySelector('#zoom').close());
// busca de locais por UF (índice JSON estático por estado)
const bUf = document.querySelector('#busca-uf'), bTxt = document.querySelector('#busca-texto'), bPri = document.querySelector('#busca-prioridade'), bSt = document.querySelector('#busca-status'), bTb = document.querySelector('#busca-tabela tbody');
const idx = {};
const norm = s => String(s).normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
async function loadUf(uf) {
  if (!idx[uf]) { bSt.textContent = 'Carregando ' + uf + '…'; const r = await fetch('dados/locais/' + uf + '.json'); idx[uf] = (await r.json()).locais; }
  return idx[uf];
}
async function buscar() {
  const uf = bUf.value; bTb.innerHTML = '';
  if (!uf) { bSt.textContent = 'Selecione um estado para começar.'; return; }
  const all = await loadUf(uf), q = norm(bTxt.value.trim()), pri = bPri.value;
  const hits = all.filter(r => (!pri || r[4] === pri) && (!q || norm(r[0]).includes(q) || norm(r[3]).includes(q) || String(r[1]) === q || String(r[2]) === q));
  const show = hits.slice(0, 150);
  bSt.textContent = `${fmt.format(hits.length)} locais encontrados em ${uf}` + (hits.length > show.length ? ` (mostrando os ${show.length} de maior pontuação; refine a busca)` : '') + '. Prioridade é ordem de observação, não probabilidade de irregularidade.';
  for (const r of show) {
    const tr = document.createElement('tr');
    // liberações manuais 2026 T1: total (não associadas · % do total); vazio fora dos locais de prioridade alta
    const man = r[12] === '' || r[12] === undefined ? '—' : `${fmt.format(r[12])} (${fmt.format(r[13])} · ${pct(r[13], r[12], 0)})`;
    [r[0], r[1], r[2], r[3] || 'local sem nome cadastrado', r[4], r[5], r[6], r[7], r[8], r[9], r[10], r[11], man].forEach((v, i) => { const td = document.createElement('td'); td.textContent = v; if (i === 4) td.className = 'pri-' + String(v).replace('é', 'e'); tr.appendChild(td); });
    const tk = document.createElement('td');
    if (r[14]) { const a = document.createElement('a'); a.href = r[14]; a.target = '_blank'; a.rel = 'noopener'; a.textContent = 'PDF ↗'; a.setAttribute('aria-label', 'Kit de campo do local ' + (r[3] || r[2])); tk.appendChild(a); } else { tk.textContent = '—'; }
    tr.appendChild(tk);
    bTb.appendChild(tr);
  }
}
if (bUf) { bUf.addEventListener('change', buscar); bPri.addEventListener('change', buscar); let t; bTxt.addEventListener('input', () => { clearTimeout(t); t = setTimeout(buscar, 200); }); }
