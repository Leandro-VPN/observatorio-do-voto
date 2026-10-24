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
document.querySelectorAll('.gallery figure').forEach(f => f.addEventListener('click', () => { const d = document.querySelector('#zoom'); d.querySelector('img').src = f.querySelector('img').src; d.querySelector('figcaption').textContent = f.querySelector('figcaption').textContent; d.showModal(); }));
document.querySelector('#zoom .close').addEventListener('click', () => document.querySelector('#zoom').close());
