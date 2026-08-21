Feature: Scorer protocol (ADR-060)
  Every eval provider — rubric, deepeval, promptfoo — implements the Scorer
  protocol so callers never depend on a specific backend.

  Background:
    Given the hive-conductor eval system is loaded

  # ---------------------------------------------------------------------------
  # AC-6 (SPEC-192): deepeval absent → graceful RubricScorer-only, no startup error
  # ---------------------------------------------------------------------------

  Scenario: RubricScorer is always available with zero optional deps
    Given a department YAML template "marketing.yaml" exists
    When I wrap its first eval dimension in a RubricScorer
    Then the scorer provider is "rubric"
    And scoring any text returns a Score with value between 0.0 and 1.0

  Scenario: DeepEvalScorer raises ImportError when deepeval is absent
    Given deepeval is not installed in this environment
    When I attempt to construct a DeepEvalScorer
    Then an ImportError is raised with "deepeval is not installed"

  Scenario: Caller falls back to RubricScorer when deepeval is absent
    Given deepeval is not installed in this environment
    When I construct a scorer with DeepEval-or-fallback logic
    Then the scorer provider is "rubric"
    And the system starts without error

  Scenario: DeepEvalScorer is available when deepeval is present
    Given deepeval is installed
    When I construct a DeepEvalScorer with criteria "Is the tone warm and first-person?"
    Then the scorer provider is "deepeval"
    And the default threshold is 0.5

  # ---------------------------------------------------------------------------
  # Protocol invariants — both providers must satisfy these
  # ---------------------------------------------------------------------------

  Scenario Outline: Score value is always in [0, 1] regardless of output
    Given a <provider> scorer
    When I score "<output>"
    Then the score value is between 0.0 and 1.0 inclusive
    And the score passed field is a boolean

    Examples:
      | provider | output                                         |
      | rubric   | Great post about repotting with care tips      |
      | rubric   | BUY NOW!!! FLASH SALE!!! LIMITED!!!            |
      | deepeval | Great post about repotting with care tips      |

  Scenario: Score provider field identifies the backend
    Given a rubric scorer
    When I score any text
    Then the score provider is "rubric"

  Scenario: Score never raises on empty string input
    Given a rubric scorer
    When I score an empty string
    Then no exception is raised
    And the score value is between 0.0 and 1.0 inclusive
