/* Royal Imóveis — o recado que a tela de login mostra quando o link falhou.
 *
 * Existe porque painel.html e index.html são páginas separadas: quem descobre
 * que o link falhou é o painel, e quem tem onde mostrar é o login. Sem canal
 * entre os dois, o painel só podia redirecionar calado — e era isso que
 * acontecia. A pessoa clicava no link, caía na tela de login sem explicação
 * nenhuma, e o caminho natural dali é pedir outro link e repetir.
 *
 * Visto em produção em 05/11/2026: um corretor entrou às 09:45; às 09:48 e às
 * 09:54 o link foi verificado de novo e falhou as duas vezes com "One-time
 * token not found". Link de acesso é de uso único, então o 403 está correto.
 * O que faltava era dizer isso a ele.
 *
 * A chave mora aqui, num lugar só, porque duas páginas a usam. Escrita à mão
 * nas duas, uma renomeação silenciaria o recado sem quebrar nada visível.
 *
 * sessionStorage, e não parâmetro na URL: o recado não fica no endereço (que
 * a pessoa pode favoritar ou recarregar) e não reaparece em visita futura.
 */

const CHAVE = "royal_aviso_login";

/**
 * Lê na URL o motivo da falha do link; "" quando não houve falha.
 *
 * TEM de ser chamada antes de criar o cliente do Supabase: ao inicializar,
 * ele consome o fragmento e limpa a URL com history.replaceState. Depois
 * disso não há mais o que ler.
 */
export function motivoDoLinkNaUrl(){
  const busca = new URLSearchParams(location.search);
  const frag  = new URLSearchParams(location.hash.replace(/^#/, ""));

  const codigo = frag.get("error_code") || busca.get("error_code") || "";
  const erro   = frag.get("error")      || busca.get("error")      || "";

  if (!codigo && !erro) return "";

  // otp_expired cobre dois casos que daqui não se distinguem: link já usado
  // ("One-time token not found") e link vencido. A mensagem fala dos dois
  // porque a ação de quem lê é a mesma — pedir outro.
  if (codigo === "otp_expired") {
    return "Esse link já foi usado ou expirou. Peça outro abaixo.";
  }

  return "Não foi possível validar esse link. Peça outro abaixo.";
}

/** Guarda o recado para a próxima página. Falha em silêncio de propósito. */
export function guardarAviso(texto){
  if (!texto) return;
  try {
    sessionStorage.setItem(CHAVE, texto);
  } catch (e) {
    // Armazenamento bloqueado (janela privada, cookies restritos). Fica sem
    // recado, que é o comportamento de antes — nunca uma tela quebrada.
  }
}

/** Lê e apaga o recado: é para aparecer uma vez, não a cada visita. */
export function lerAviso(){
  try {
    const texto = sessionStorage.getItem(CHAVE);
    if (texto) sessionStorage.removeItem(CHAVE);
    return texto || "";
  } catch (e) {
    return "";
  }
}
