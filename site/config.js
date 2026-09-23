// Royal Imóveis — configuração do cliente Supabase
//
// ATENÇÃO AO QUE VAI AQUI
// -----------------------
// Só a chave ANÔNIMA (anon / publishable). Ela é feita para viver no
// navegador: todo visitante recebe uma cópia. O que impede alguém de ler
// dados alheios com ela é a RLS, provada em supabase/tests/02 e 03.
//
// A service_role key NUNCA entra neste arquivo, nem em nenhum outro que o
// navegador baixe. Ela ignora RLS e GRANT. O lugar dela é o .env do sync e
// os secrets do GitHub Actions.
//
// Por isso este arquivo pode ser versionado: ele não contém segredo.

window.ROYAL_CONFIG = {
  // Settings -> API -> Project URL
  SUPABASE_URL: "https://SEU_PROJECT_REF.supabase.co",

  // Settings -> API -> anon / public  (NÃO a service_role)
  SUPABASE_ANON_KEY: "COLE_AQUI_A_CHAVE_ANON",
};
