/* ---------------- Devices: the machines on your network, in a window of their own ----------------
   Asked for as "have these devices in the device hub in Bento". The same list as Settings →
   Network (netPaint draws into every .devhub-box), so the two never disagree: each machine,
   what it is to Bento, its switches as last read, Controls, Install and Remove. */
async function renderDevices(body,w){
  const pb=panelShell(body,{title:'Devices',sub:'The machines on your network'});
  pb.innerHTML=`<div class="devhub-box" id="devhub-${esc(w&&w.id||'0')}"><p class="mut">…</p></div>`;
  await netPaint();
}
