const LADOS = { direita: "para a direita", esquerda: "para a esquerda", cima: "para cima", baixo: "para baixo" };

const estado = {
    posicao: "direita",
    dispositivos: [],
    escolhido: null,
    bloqueado: false,
    eu: { nome: "Este computador", tamanho: [1366, 768] },
};

function mostrarVista(nome) {
    document.querySelectorAll(".view").forEach((v) => mostrar(v, v.id === nome));
}

function textoTamanho(tamanho) {
    return `<small>${tamanho[0]} × ${tamanho[1]}</small>`;
}

function dispositivoEscolhido() {
    return estado.dispositivos.find((d) => d.chave === estado.escolhido);
}

// ---------- disposição dos ecrãs

function desenharDisposicao() {
    $("#ecraLocal").innerHTML = `${escapar(estado.eu.nome)}${textoTamanho(estado.eu.tamanho)}`;
    const disp = dispositivoEscolhido();
    document.querySelectorAll("#disposicao .zone").forEach((z) => {
        const ativa = z.dataset.pos === estado.posicao;
        z.classList.toggle("on", ativa);
        z.innerHTML = ativa ? escapar(disp ? disp.nome : "Outro") : "";
    });
}

document.querySelectorAll("#disposicao .zone").forEach((z) => {
    z.addEventListener("click", () => {
        estado.posicao = z.dataset.pos;
        desenharDisposicao();
        enviar("preferencias", { posicao: estado.posicao });
    });
});

// ---------- dispositivos

function desenharDispositivos() {
    const lista = $("#dispositivos");
    lista.innerHTML = "";
    estado.dispositivos.forEach((d) => {
        const li = document.createElement("li");
        li.classList.toggle("on", d.chave === estado.escolhido);
        li.innerHTML = `
            <div class="grow">
                <span class="name">${escapar(d.nome)}</span>
                <span class="ip num">${escapar(d.ip)}${d.emparelhado ? " · emparelhado" : ""}</span>
            </div>
            ${d.via === "cabo" ? '<span class="tag">cabo</span>' : ""}`;
        li.addEventListener("click", () => {
            estado.escolhido = d.chave;
            $("#campoIp").value = "";
            desenharDispositivos();
            desenharDisposicao();
            atualizarBotao();
        });
        lista.appendChild(li);
    });
    mostrar($("#semDispositivos"), estado.dispositivos.length === 0);
}

function atualizarBotao() {
    const temAlvo = Boolean(dispositivoEscolhido()) || $("#campoIp").value.trim() !== "";
    $("#btnEstender").disabled = !temAlvo || estado.bloqueado;
}

$("#btnProcurar").addEventListener("click", () => enviar("procurar"));
$("#campoIp").addEventListener("input", atualizarBotao);

// ---------- ligar

function opcoes() {
    return {
        resolucao: $("#resolucao").value,
        qualidade: Number($("#qualidade").value),
        hw: $("#hw").checked,
    };
}

$("#btnEstender").addEventListener("click", () => {
    const ip = $("#campoIp").value.trim();
    const disp = dispositivoEscolhido();
    $("#erroInicio").textContent = "";
    if (disp && !ip) {
        enviar("preferencias", { ultimo: disp.id });
    }
    enviar("ligar", {
        alvo: ip ? { ip } : { ip: disp.ip, porta: disp.porta, nome: disp.nome },
        posicao: estado.posicao,
        ...opcoes(),
    });
});

["resolucao", "qualidade", "hw"].forEach((id) => {
    $(`#${id}`).addEventListener("change", () => enviar("preferencias", opcoes()));
});

$("#btnCancelar").addEventListener("click", () => enviar("cancelar"));
$("#btnCancelarCodigo").addEventListener("click", () => enviar("cancelar"));
$("#btnParar").addEventListener("click", () => {
    $("#btnParar").disabled = true;
    enviar("parar");
});

$("#campoCodigo").addEventListener("input", (e) => {
    e.target.value = e.target.value.replace(/\D/g, "").slice(0, 6);
    $("#btnConfirmar").disabled = e.target.value.length !== 6;
    if (e.target.value.length === 6) {
        confirmarCodigo();
    }
});
$("#btnConfirmar").addEventListener("click", confirmarCodigo);

function confirmarCodigo() {
    const codigo = $("#campoCodigo").value;
    if (codigo.length === 6) {
        $("#tituloLigar").textContent = "A confirmar o código…";
        mostrarVista("a_ligar");
        enviar("codigo", { codigo });
    }
}

// ---------- menu

$("#btnMenu").addEventListener("click", () => mostrar($("#menu"), $("#menu").hidden));
document.addEventListener("click", (e) => {
    if (!e.target.closest(".menu")) {
        mostrar($("#menu"), false);
    }
});
$("#btnEsquecer").addEventListener("click", () => {
    mostrar($("#menu"), false);
    enviar("esquecer");
});
$("#btnDesinstalar").addEventListener("click", () => {
    mostrar($("#menu"), false);
    mostrar($("#janelaDesinstalar"));
});
$("#btnNaoDesinstalar").addEventListener("click", () => mostrar($("#janelaDesinstalar"), false));
$("#btnSimDesinstalar").addEventListener("click", () => enviar("desinstalar", { tudo: $("#apagarTudo").checked }));

// ---------- mensagens do Python

quando("inicio", (d) => {
    estado.eu = { nome: d.nomeHost, tamanho: d.tamanhoLocal };
    estado.posicao = d.prefs.posicao || "direita";
    estado.ultimo = d.prefs.ultimo;
    $("#resolucao").value = d.prefs.resolucao || "auto";
    $("#qualidade").value = String(d.prefs.qualidade || 6000);
    $("#hw").checked = Boolean(d.prefs.hw);
    mostrar($("#linhaHw"), d.hwDisponivel);
    $("#rodape").textContent = `DexLan ${d.versao} · ${d.sistema}`;
    estado.bloqueado = Boolean(d.erroEcra);
    $("#erroInicio").textContent = d.erroEcra || "";
    desenharDisposicao();
    atualizarBotao();
});

quando("a_procurar", (ocupado) => {
    $("#btnProcurar").textContent = ocupado ? "A procurar…" : "Procurar";
    $("#btnProcurar").disabled = ocupado;
});

quando("dispositivos", (lista) => {
    estado.dispositivos = lista.map((d) => ({ ...d, chave: d.id || d.ip }));
    if (!dispositivoEscolhido()) {
        const ultimo = estado.dispositivos.find((d) => d.id === estado.ultimo);
        estado.escolhido = (ultimo || estado.dispositivos[0] || {}).chave || null;
    }
    desenharDispositivos();
    desenharDisposicao();
    atualizarBotao();
});

quando("vista", (d) => {
    if (d.nome === "inicio") {
        $("#erroInicio").textContent = d.erro || "";
    }
    if (d.nome === "a_ligar") {
        $("#tituloLigar").textContent = `A ligar a ${d.alvo}`;
        $("#textoLigar").textContent = d.ip;
    }
    if (d.nome === "codigo") {
        $("#tituloCodigo").textContent = `Escreve o código que aparece em ${d.alvo}`;
        $("#campoCodigo").value = "";
        $("#btnConfirmar").disabled = true;
        $("#erroCodigo").textContent = d.restantes < 3 ? `Código errado. Restam ${d.restantes} tentativas.` : "";
        setTimeout(() => $("#campoCodigo").focus(), 50);
    }
    if (d.nome === "activo") {
        desenharActivo(d);
    }
    mostrarVista(d.nome);
});

function desenharActivo(d) {
    $("#nomeActivo").textContent = d.alvo;
    $("#btnParar").disabled = false;
    const outro = `<div class="zone on">${escapar(d.alvo)}${textoTamanho(d.tamanho)}</div>`;
    const local = `<div class="screen">${escapar(estado.eu.nome)}${textoTamanho(estado.eu.tamanho)}</div>`;
    const primeiro = d.posicao === "esquerda" || d.posicao === "cima";
    const caixa = $("#disposicaoActiva");
    caixa.className = "layout active" + (d.posicao === "cima" || d.posicao === "baixo" ? " vertical" : "");
    caixa.innerHTML = primeiro ? outro + local : local + outro;
    $("#dicaActivo").textContent = `Arrasta janelas ${LADOS[d.posicao]}. Quando parares, voltam todas para este ecrã.`;
    estadoLigacao(d.via === "cabo" ? "Ligado por cabo" : "Ligado pela rede", "ok");
    ["#numFps", "#numAtraso", "#numMbps"].forEach((s) => ($(s).textContent = "–"));
}

function estadoLigacao(texto, tipo) {
    $("#estadoActivo").innerHTML = `<span class="dot"></span>${texto}`;
    $("#estadoActivo").classList.toggle("warn", tipo === "aviso");
    $("#disposicaoActiva").classList.toggle("reconnecting", tipo === "aviso");
}

quando("sessao", (d) => {
    if (d.estado === "activo") {
        estadoLigacao(d.via === "cabo" ? "Ligado por cabo" : "Ligado pela rede", "ok");
    } else if (d.estado === "a_religar") {
        estadoLigacao("Ligação perdida, a tentar religar…", "aviso");
    }
});

quando("numeros", (n) => {
    $("#numFps").textContent = Math.round(n.fps);
    $("#numAtraso").textContent = n.rtt === null ? "–" : Math.round(n.rtt);
    $("#numMbps").textContent = (n.kbps / 1000).toFixed(1);
});

painelCabo($("#painelCabo"));
enviar("pronto");

// Aberto no browser (fora da aplicação): dados de exemplo para editar o visual.
if (!dentroDaApp()) {
    receber("inicio", {
        nomeHost: "meu-pc", tamanhoLocal: [1366, 768], versao: "dev", sistema: "Browser",
        prefs: { posicao: "direita" }, hwDisponivel: true,
    });
    receber("dispositivos", [
        { id: "a", nome: "portatil-antigo", ip: "169.254.77.77", via: "cabo", emparelhado: true },
        { id: "b", nome: "sala", ip: "192.168.1.20", via: "rede" },
    ]);
    receber("cabo", {
        disponivel: true, texto: "Ligado por cabo em enp0s31f6", ip: "169.254.49.121/16",
        definicoes: { ativo: true, modo: "auto", endereco: "192.168.50.1", mascara: "255.255.255.0" },
    });
}
