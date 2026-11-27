// Comunicação com o Python.
// Página -> Python: enviar("accao", dados)
// Python -> Página: quando("evento", funcao)
const ouvintes = {};

function dentroDaApp() {
    return Boolean(window.webkit?.messageHandlers?.dexlan);
}

function enviar(accao, dados = {}) {
    const msg = JSON.stringify({ accao, dados });
    if (dentroDaApp()) {
        window.webkit.messageHandlers.dexlan.postMessage(msg);
    } else {
        console.log("enviar:", accao, dados);
    }
}

function quando(evento, funcao) {
    ouvintes[evento] = funcao;
}

window.receber = (evento, dados) => {
    if (ouvintes[evento]) {
        ouvintes[evento](dados);
    }
};

function $(seletor) {
    return document.querySelector(seletor);
}

function mostrar(el, visivel = true) {
    el.hidden = !visivel;
}

// Escapa texto vindo da rede antes de o pôr em innerHTML.
function escapar(texto) {
    const div = document.createElement("div");
    div.textContent = String(texto ?? "");
    return div.innerHTML;
}
