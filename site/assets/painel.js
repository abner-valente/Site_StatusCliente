/* Royal Imóveis — extraído de painel.html.
 * Vive em arquivo próprio para que a CSP possa proibir script embutido:
 * sem 'unsafe-inline' em script-src, um <script> no HTML não executa.
 */
// Esta tela existe porque um cliente pode ter mais de um imóvel: a restrição
// de e-mail é unique (processo_id, email), por processo e não global. Uma tela
// que supusesse um processo por login quebraria na primeira recompra.
//
// Com um imóvel só, ela redireciona direto para o acompanhamento.
import { criarClienteRoyal } from "./cliente.js";

const cfg = window.ROYAL_CONFIG || {};
const app = document.getElementById("app");

const MARCA = '<div class="brand"><img src="assets/royal-logo.png" alt="Royal Imóveis RJ"></div>';

// Dado vindo do banco vai para o DOM como texto, nunca como HTML.
function esc(s){
  return String(s ?? "").replace(/[&<>"']/g, c => (
    { "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[c]
  ));
}

function estado(titulo, texto){
  app.innerHTML = `<div class="estado"><h2>${esc(titulo)}</h2><p>${esc(texto)}</p></div>`;
}

let sb;
try {
  sb = criarClienteRoyal(cfg);
} catch (e) {
  estado("Não foi possível iniciar", e.message);
}

if (sb) {

  // O magic link volta com a sessão no fragmento da URL; o cliente do
  // Supabase a consome sozinho. getSession espera isso terminar.
  const { data: { session } } = await sb.auth.getSession();

  if (!session) {
    location.replace("index.html");
  } else {
    // Sem filtro de titular na consulta: quem filtra é a RLS, no banco.
    // Um erro aqui não consegue mostrar processo alheio.
    const { data: processos, error } = await sb
      .from("processos")
      .select("id, imovel, modalidade, data_assinatura, ativo")
      .order("data_assinatura", { ascending: false });

    if (error) {
      console.error("Falha ao carregar processos:", error);
      estado("Não foi possível carregar",
             "Tente novamente em instantes ou fale com seu corretor.");
    } else if (!processos || processos.length === 0) {
      // Sessão válida sem processo: e-mail autenticado que não é titular de
      // nada. Acontece se o cadastro na planilha ainda não foi feito.
      estado("Nenhuma negociação encontrada",
             "Seu acesso está ativo, mas ainda não há negociação vinculada a este e-mail. Fale com seu corretor Royal Imóveis.");
    } else if (processos.length === 1) {
      location.replace("acompanhamento.html?p=" + encodeURIComponent(processos[0].id));
    } else {
      renderLista(processos, session.user.email);
    }

    function renderLista(lista, email){
      const itens = lista.map(p => {
        const data = p.data_assinatura
          ? new Date(p.data_assinatura + "T00:00:00").toLocaleDateString("pt-BR")
          : "—";
        const modalidade = p.modalidade === "avista" ? "À vista" : "Financiado";
        return '<a class="item-processo" href="acompanhamento.html?p='
          + encodeURIComponent(p.id) + '">'
          + '<div><b>' + esc(p.imovel) + '</b>'
          + '<div class="detalhe">Assinatura em ' + esc(data) + '</div></div>'
          + '<span class="selo">' + esc(modalidade) + '</span></a>';
      }).join("");

      app.innerHTML =
        '<div class="topbar"><div class="heading">'
        + '<p class="eyebrow">Acompanhamento</p>'
        + '<h1>Suas negociações</h1>'
        + '<p class="meta">' + esc(email) + ' · ' + lista.length + ' negociações</p>'
        + '</div>' + MARCA + '</div>'
        + '<div class="lista">' + itens + '</div>'
        + '<div style="margin-top:28px"><button class="secundario" id="sair">Sair</button></div>';

      document.getElementById("sair").addEventListener("click", async () => {
        await sb.auth.signOut();
        location.replace("index.html");
      });
    }
  }
}
