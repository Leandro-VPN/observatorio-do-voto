// Gerado por scripts/build_site.py a partir de relatorios/fiscalizacao/varredura/resumo_por_eleicao.csv. Não editar à mão.
const records = {"P2026": {"secoes": 384794, "com_comportamento": 36075, "tardia": 32961, "manual": 4275, "local_com_comportamento": 15593, "local_dif_real": 664, "local_comuns": 293231, "local_comuns_real": 7175, "local_favor_A": 506, "local_favor_B": 158, "local_comuns_favor_A": 3901, "local_comuns_favor_B": 3274, "cmp_municipio": 10346}, "P2022": {"secoes": 366601, "com_comportamento": 38473, "tardia": 35628, "manual": 8635, "local_com_comportamento": 16013, "local_dif_real": 549, "local_comuns": 273894, "local_comuns_real": 6994, "local_favor_A": 346, "local_favor_B": 203, "local_comuns_favor_A": 4014, "local_comuns_favor_B": 2980, "cmp_municipio": 11313}, "P2022b": {"secoes": 366600, "com_comportamento": 3691, "tardia": 70, "manual": 3629, "local_com_comportamento": 2346, "local_dif_real": 78, "local_comuns": 305171, "local_comuns_real": 7871, "local_favor_A": 41, "local_favor_B": 37, "local_comuns_favor_A": 4573, "local_comuns_favor_B": 3298, "cmp_municipio": 704}, "M2024": {"secoes": 376447, "com_comportamento": 4433, "tardia": 887, "manual": 3641, "local_com_comportamento": 2692, "local_dif_real": 76, "local_comuns": 313846, "local_comuns_real": 6344, "local_favor_A": 45, "local_favor_B": 31, "local_comuns_favor_A": 3239, "local_comuns_favor_B": 3105, "cmp_municipio": 905}, "M2024b": {"secoes": 77157, "com_comportamento": 741, "tardia": 3, "manual": 738, "local_com_comportamento": 681, "local_dif_real": 21, "local_comuns": 74294, "local_comuns_real": 1334, "local_favor_A": 10, "local_favor_B": 11, "local_comuns_favor_A": 695, "local_comuns_favor_B": 639, "cmp_municipio": 32}};
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
  const key = '4cc4708e-e291-4012-ab41-3c67eab901c9';
  try { await navigator.clipboard.writeText(key); document.querySelector('#copy-status').textContent = 'Chave Pix copiada. Confira o destinatário no aplicativo do seu banco.'; }
  catch { document.querySelector('#copy-status').textContent = 'Chave Pix: ' + key; }
});
const homeBtn = document.querySelector('#copy-pix-home');
if (homeBtn) homeBtn.addEventListener('click', async () => {
  const key = '4cc4708e-e291-4012-ab41-3c67eab901c9';
  try { await navigator.clipboard.writeText(key); document.querySelector('#copy-status-home').textContent = 'Chave Pix copiada. Confira o destinatário no aplicativo do seu banco.'; }
  catch { document.querySelector('#copy-status-home').textContent = 'Chave Pix: ' + key; }
});
document.querySelectorAll('.gallery figure').forEach(f => f.addEventListener('click', () => { const d = document.querySelector('#zoom'); d.querySelector('img').src = f.querySelector('img').src; d.querySelector('figcaption').textContent = f.querySelector('figcaption').textContent; d.showModal(); }));
document.querySelector('#zoom .close').addEventListener('click', () => document.querySelector('#zoom').close());
