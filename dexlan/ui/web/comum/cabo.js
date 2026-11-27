// Cartão "Cabo de rede", usado no host e no receiver.
function painelCabo(raiz) {
    raiz.innerHTML = `
        <div class="card-head">
            <h2>Cabo de rede</h2>
            <label class="switch" title="Configurar sozinho quando ligares o cabo">
                <input type="checkbox" class="cabo-ativo"><span></span>
            </label>
        </div>
        <p class="cabo-estado hint"></p>
        <p class="cabo-ip num"></p>
        <details class="cabo-config">
            <summary class="link">Configurar endereço</summary>
            <div class="seg cabo-modo">
                <button data-modo="auto">Automático</button>
                <button data-modo="manual">Manual</button>
            </div>
            <p class="hint cabo-dica-auto">Os dois computadores escolhem um endereço 169.254.x.x sozinhos.</p>
            <div class="cabo-manual">
                <div class="field"><label>IP deste computador</label><input class="cabo-endereco num" placeholder="192.168.50.1"></div>
                <div class="field"><label>Máscara</label><input class="cabo-mascara num" placeholder="255.255.255.0"></div>
                <p class="hint">No outro computador usa um IP da mesma rede, por exemplo 192.168.50.2.</p>
            </div>
            <button class="btn cabo-aplicar">Aplicar</button>
            <p class="error cabo-erro"></p>
        </details>`;

    const q = (s) => raiz.querySelector(s);
    let modo = "auto";

    function escolherModo(m) {
        modo = m;
        raiz.querySelectorAll(".cabo-modo button").forEach((b) => b.classList.toggle("on", b.dataset.modo === m));
        mostrar(q(".cabo-manual"), m === "manual");
        mostrar(q(".cabo-dica-auto"), m === "auto");
    }

    q(".cabo-ativo").addEventListener("change", (e) => enviar("cabo", { ativo: e.target.checked }));
    raiz.querySelectorAll(".cabo-modo button").forEach((b) => b.addEventListener("click", () => escolherModo(b.dataset.modo)));
    q(".cabo-aplicar").addEventListener("click", () => {
        q(".cabo-erro").textContent = "";
        q(".cabo-aplicar").disabled = true;
        enviar("cabo", {
            modo,
            endereco: q(".cabo-endereco").value.trim(),
            mascara: q(".cabo-mascara").value.trim(),
            aplicar: true,
        });
    });

    quando("cabo", (st) => {
        q(".cabo-estado").textContent = st.texto;
        q(".cabo-ip").textContent = st.ip ? `IP: ${st.ip}` : "";
        q(".cabo-ativo").checked = st.definicoes.ativo;
        q(".cabo-ativo").disabled = !st.disponivel;
        q(".cabo-config").hidden = !st.disponivel;
        if (!q(".cabo-config").open) {
            escolherModo(st.definicoes.modo);
            q(".cabo-endereco").value = st.definicoes.endereco;
            q(".cabo-mascara").value = st.definicoes.mascara;
        }
    });
    quando("resultadoCabo", (r) => {
        q(".cabo-aplicar").disabled = false;
        q(".cabo-erro").textContent = r.erro || "";
        if (!r.erro) {
            q(".cabo-config").open = false;
        }
    });
    escolherModo("auto");
}
