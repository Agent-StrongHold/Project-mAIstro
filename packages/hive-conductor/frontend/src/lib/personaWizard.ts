/** Persona Wizard form shapes (#336). Under `lib/` for typed-client: the
 * wizard's drafts mirror `services/persona_authoring.py`'s writable
 * template store, so they are wire-adjacent shapes rather than
 * page-local declarations. */

export type WizardAgent = {
  agent: string;
  role: string;
  toolsText: string;
  skillsText: string;
};

export type WizardInterviewQuestion = {
  field: string;
  agent: string;
  question: string;
};
