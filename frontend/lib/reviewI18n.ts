/**
 * English / Portuguese strings for the standalone /review page, plus a
 * tiny hook that remembers the reviewer's choice in localStorage.
 *
 * Pair text itself is translated server-side (question_pt / answer_pt,
 * filled by scripts/translate_pairs.py); this file covers the interface.
 */

import { useCallback, useEffect, useState } from "react";

export type ReviewLang = "en" | "pt";

const STORAGE_KEY = "vedanta:review-lang";

export const reviewStrings = {
  en: {
    title: "Persona Pairs Review",
    switchTo: "Português",
    switchLabel: "Mudar para português",
    signInPrompt:
      "Sign in above with the account you were given to start reviewing.",
    noAccess: "This account doesn't have reviewer access.",
    intro:
      "For each pair: read the question and answer, then mark Approve, Reject, or Edit. Nothing is used for training until it's approved here.",
    filters: {
      pending: "pending",
      approved: "approved",
      rejected: "rejected",
      "": "all",
    } as Record<string, string>,
    status: {
      pending: "pending",
      approved: "approved",
      rejected: "rejected",
    } as Record<string, string>,
    showing: (n: number, total: number) => `showing ${n} of ${total}`,
    empty: "Nothing here — upload a transcript or switch the filter above.",
    q: "Q",
    approve: "Approve",
    reject: "Reject",
    edit: "Edit",
    save: "Save",
    cancel: "Cancel",
    words: "words",
    reviewedBy: "reviewed by",
    notTranslated: "",
    showOriginal: "",
    hideOriginal: "",
    editingTranslation: "",
    loading: "Loading…",
    loadMore: (n: number) => `Load ${n} more`,
    auth: {
      email: "email",
      password: "password",
      signIn: "Sign in",
      signOut: "Sign out",
      failed: "Authentication failed.",
    },
  },
  pt: {
    title: "Revisão de Pares de Perguntas e Respostas",
    switchTo: "English",
    switchLabel: "Switch to English",
    signInPrompt:
      "Entre acima com a conta que você recebeu para começar a revisar.",
    noAccess: "Esta conta não tem acesso de revisor.",
    intro:
      "Para cada par: leia a pergunta e a resposta e marque Aprovar, Rejeitar ou Editar. Nada é usado no treinamento até ser aprovado aqui.",
    filters: {
      pending: "pendentes",
      approved: "aprovados",
      rejected: "rejeitados",
      "": "todos",
    } as Record<string, string>,
    status: {
      pending: "pendente",
      approved: "aprovado",
      rejected: "rejeitado",
    } as Record<string, string>,
    showing: (n: number, total: number) => `mostrando ${n} de ${total}`,
    empty: "Nada aqui — envie uma transcrição ou mude o filtro acima.",
    q: "P",
    approve: "Aprovar",
    reject: "Rejeitar",
    edit: "Editar",
    save: "Salvar",
    cancel: "Cancelar",
    words: "palavras",
    reviewedBy: "revisado por",
    notTranslated:
      "Tradução ainda não disponível — mostrando o original em inglês.",
    showOriginal: "Ver original em inglês",
    hideOriginal: "Ocultar original",
    editingTranslation:
      "Você está editando a tradução em português. O original em inglês não muda.",
    loading: "Carregando…",
    loadMore: (n: number) => `Carregar mais ${n}`,
    auth: {
      email: "e-mail",
      password: "senha",
      signIn: "Entrar",
      signOut: "Sair",
      failed: "Falha na autenticação.",
    },
  },
};

export type ReviewStrings = (typeof reviewStrings)["en"];

const listeners = new Set<(lang: ReviewLang) => void>();

function readLang(): ReviewLang {
  try {
    // A shared link like /review?lang=pt opens in that language.
    const fromUrl = new URLSearchParams(window.location.search).get("lang");
    if (fromUrl === "pt" || fromUrl === "en") {
      window.localStorage.setItem(STORAGE_KEY, fromUrl);
      return fromUrl;
    }
    return window.localStorage.getItem(STORAGE_KEY) === "pt" ? "pt" : "en";
  } catch {
    return "en";
  }
}

/** Current review-page language, shared across components and persisted. */
export function useReviewLang(): [ReviewLang, (lang: ReviewLang) => void] {
  const [lang, setLangState] = useState<ReviewLang>("en");

  useEffect(() => {
    setLangState(readLang());
    listeners.add(setLangState);
    return () => {
      listeners.delete(setLangState);
    };
  }, []);

  const setLang = useCallback((next: ReviewLang) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* private mode etc. — still switch for this visit */
    }
    for (const cb of listeners) cb(next);
  }, []);

  return [lang, setLang];
}
