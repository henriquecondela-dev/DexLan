function mostrarCodigo(codigo) {
    const caixa = $("#codigo");
    caixa.innerHTML = "";
    [...codigo].forEach((digito) => {
        const span = document.createElement("span");
        span.textContent = digito;
        caixa.appendChild(span);
    });
    mostrar(caixa, codigo.length > 0);
}

$("#btnRede").addEventListener("click", () => mostrar($("#gaveta"), $("#gaveta").hidden));
$("#btnFecharGaveta").addEventListener("click", () => mostrar($("#gaveta"), false));
$("#btnEcraInteiro").addEventListener("click", () => enviar("ecra_inteiro"));

quando("inicio", (d) => {
    $("#nome").textContent = d.nome;
    document.title = `DexLan Receiver: ${d.nome}`;
    mostrar($("#btnRede"), d.cabo);
});

quando("estado", (e) => {
    $("#titulo").textContent = e.titulo;
    $("#texto").textContent = e.texto;
    mostrarCodigo(e.codigo || "");
});

quando("rede", (r) => {
    $("#enderecos").textContent = r.enderecos.length ? `IP ${r.enderecos.join(", ")}` : "Sem rede";
    $("#linhaCabo").textContent = r.cabo ? r.cabo.texto : "";
    if (r.cabo) {
        receber("cabo", r.cabo);
    }
});

painelCabo($("#painelCabo"));
enviar("pronto");

// Aberto no browser (fora da aplicação): dados de exemplo para editar o visual.
if (!dentroDaApp()) {
    receber("inicio", { nome: "portatil-antigo", cabo: true });
    receber("estado", { titulo: "meu-pc quer usar este ecrã", texto: "Escreve este código em meu-pc. Se não foste tu, ignora.", codigo: "431754" });
    receber("rede", {
        enderecos: ["169.254.77.77", "192.168.1.20"],
        cabo: {
            disponivel: true, texto: "Ligado por cabo em eth0", ip: "169.254.77.77/16",
            definicoes: { ativo: true, modo: "auto", endereco: "192.168.50.2", mascara: "255.255.255.0" },
        },
    });
}
