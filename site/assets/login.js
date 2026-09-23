/* Royal Imóveis — extraído de index.html.
 * Vive em arquivo próprio para que a CSP possa proibir script embutido:
 * sem 'unsafe-inline' em script-src, um <script> no HTML não executa.
 */
import { criarClienteRoyal } from "./cliente.js";

const cfg = window.ROYAL_CONFIG || {};
const form     = document.getElementById("form-login");
const campo    = document.getElementById("email");
const botao    = document.getElementById("botao");
const avisoOk  = document.getElementById("aviso-ok");
const avisoErr = document.getElementById("aviso-erro");

function mostrar(el, texto){
  el.textContent = texto;
  el.hidden = false;
}
function limpar(){
  avisoOk.hidden = true;
  avisoErr.hidden = true;
}

let sb;
try {
  sb = criarClienteRoyal(cfg);
} catch (e) {
  botao.disabled = true;
  mostrar(avisoErr, e.message);
}

if (sb) {

  // Quem já tem sessão válida não precisa ver esta tela.
  const { data: { session } } = await sb.auth.getSession();
  if (session) location.replace("painel.html");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    limpar();

    const email = campo.value.trim().toLowerCase();
    if (!email || !email.includes("@")) {
      mostrar(avisoErr, "Digite um e-mail válido.");
      campo.focus();
      return;
    }

    botao.disabled = true;
    botao.textContent = "Enviando…";

    const { error } = await sb.auth.signInWithOtp({
      email,
      options: {
        emailRedirectTo: new URL("painel.html", location.href).href,
        // Impede que um e-mail desconhecido crie conta. É a segunda barreira:
        // a primeira é o cadastro público desligado no painel do Supabase.
        // Sem isso, qualquer pessoa criaria conta com a chave anon, que é
        // pública por natureza.
        shouldCreateUser: false,
      },
    });

    botao.disabled = false;
    botao.textContent = "Receber link de acesso";

    if (error) {
      // A mensagem ao usuário é sempre a mesma, com ou sem erro: dizer
      // "e-mail não cadastrado" confirmaria a terceiros quem é cliente da
      // Royal. O detalhe fica no console, para suporte.
      console.warn("Falha no envio do link:", error.message);
    }

    form.hidden = true;
    mostrar(avisoOk,
      "Se este e-mail estiver cadastrado na sua negociação, o link de acesso " +
      "chega em instantes. Confira também a caixa de spam.");
  });
}
