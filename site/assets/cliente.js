/* Royal Imóveis — criação do cliente Supabase, com trava de segurança.
 *
 * Existe por um motivo só: impedir que a service_role key chegue ao navegador.
 *
 * As duas chaves ficam lado a lado na mesma tela do painel do Supabase e são
 * fáceis de confundir. A anon é inofensiva — todo visitante recebe uma cópia e
 * a RLS é que decide o que ela enxerga. A service_role ignora RLS e GRANT:
 * publicada num arquivo que o navegador baixa, ela entrega os dados de todos
 * os compradores a qualquer pessoa que abrir o site.
 *
 * Como o estrago é irreversível (a chave fica no histórico de quem baixou), a
 * verificação acontece antes de qualquer requisição.
 */

// TODO endurecer: fixar a versão exata do supabase-js e adicionar integridade
// (SRI) antes de colocar clientes reais.
import { createClient } from "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm";

/** Decodifica o payload de um JWT sem validar assinatura. Só para inspeção. */
function payloadDoJwt(chave){
  const partes = String(chave).split(".");
  if (partes.length !== 3) return null;
  try {
    const base64 = partes[1].replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(atob(base64));
  } catch {
    return null;
  }
}

/** true quando a chave é claramente secreta (service_role ou sb_secret_). */
export function chaveEhSecreta(chave){
  if (!chave) return false;
  if (String(chave).startsWith("sb_secret_")) return true;

  const payload = payloadDoJwt(chave);
  if (payload && payload.role && payload.role !== "anon") return true;

  return false;
}

/** true quando config.js ainda está com os valores de exemplo. */
export function configPendente(cfg){
  return !cfg
    || !cfg.SUPABASE_URL
    || !cfg.SUPABASE_ANON_KEY
    || cfg.SUPABASE_URL.includes("SEU_PROJECT_REF")
    || cfg.SUPABASE_ANON_KEY.includes("COLE_AQUI");
}

/**
 * Monta o cliente. Lança erro com mensagem legível quando algo está errado,
 * em vez de deixar a página falhar de um jeito difícil de diagnosticar.
 */
export function criarClienteRoyal(cfg){
  if (configPendente(cfg)) {
    throw new Error(
      "Configuração pendente: preencha site/config.js com a URL do projeto e a chave anon."
    );
  }

  if (chaveEhSecreta(cfg.SUPABASE_ANON_KEY)) {
    throw new Error(
      "CHAVE ERRADA: isto parece a service_role (ou uma secret key), que ignora " +
      "a RLS e nunca pode ir para o navegador. Troque por a chave anon / " +
      "publishable em Settings -> API Keys. Se esta chave já foi publicada em " +
      "algum lugar, gere outra no painel."
    );
  }

  return createClient(cfg.SUPABASE_URL, cfg.SUPABASE_ANON_KEY);
}
