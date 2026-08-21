Feature: Declarative check vocabulary (ADR-060)
  The vocabulary lets criteria be expressed as YAML ops with no Python.
  Every op takes a text string and returns a bool.

  # ---------------------------------------------------------------------------
  # AC-2 (SPEC-192): new domain = one YAML file, no Python changes
  # ---------------------------------------------------------------------------

  Scenario: A new department is added with only a YAML file
    Given a new YAML template "templates/test_new_dept.yaml" with kind "department" and name "test_new_dept"
    When I call all_departments()
    Then "test_new_dept" appears in the department registry
    And I remove the temporary template

  # ---------------------------------------------------------------------------
  # keywords_any
  # ---------------------------------------------------------------------------

  Scenario Outline: keywords_any matches when at least one word is present
    Given a check op "keywords_any" with words ["calm", "grounding", "routine"]
    When I evaluate "<text>"
    Then the result is <expected>

    Examples:
      | text                              | expected |
      | a grounding morning ritual        | True     |
      | buy now limited offer             | False    |
      | calm and consistent routine care  | True     |
      | GROUNDING practice daily          | True     |

  Scenario: keywords_any with an empty word list always returns False
    Given a check op "keywords_any" with an empty word list
    When I evaluate "any text at all"
    Then the result is False

  # ---------------------------------------------------------------------------
  # keywords_none
  # ---------------------------------------------------------------------------

  Scenario: keywords_none blocks when a forbidden word is present
    Given a check op "keywords_none" with words ["cure", "diagnose", "treats"]
    When I evaluate "this plant cures anxiety"
    Then the result is False

  Scenario: keywords_none passes when no forbidden words appear
    Given a check op "keywords_none" with words ["cure", "diagnose", "treats"]
    When I evaluate "water your plant weekly for a calm routine"
    Then the result is True

  # ---------------------------------------------------------------------------
  # word_count
  # ---------------------------------------------------------------------------

  Scenario: word_count max enforced
    Given a check op "word_count" with max 5
    When I evaluate "one two three four five six"
    Then the result is False

  Scenario: word_count max passes at boundary
    Given a check op "word_count" with max 5
    When I evaluate "one two three four five"
    Then the result is True

  Scenario: word_count min enforced
    Given a check op "word_count" with min 3
    When I evaluate "one two"
    Then the result is False

  # ---------------------------------------------------------------------------
  # regex / regex_absent
  # ---------------------------------------------------------------------------

  Scenario: regex matches when pattern found
    Given a check op "regex" with pattern "DM to order"
    When I evaluate "Plants from $12 — DM to order"
    Then the result is True

  Scenario: regex_absent passes when pattern not found
    Given a check op "regex_absent" with pattern "(death|murder)" and flags "i"
    When I evaluate "a calm repotting guide"
    Then the result is True

  Scenario: regex_absent fails when pattern found
    Given a check op "regex_absent" with pattern "(death|murder)" and flags "i"
    When I evaluate "death metal playlist"
    Then the result is False

  # ---------------------------------------------------------------------------
  # any / all combinators
  # ---------------------------------------------------------------------------

  Scenario: any combinator passes when at least one sub-op passes
    Given a check op "any" combining keywords_any["calm"] and keywords_any["local pickup"]
    When I evaluate "local pickup available this weekend"
    Then the result is True

  Scenario: all combinator fails when any sub-op fails
    Given a check op "all" combining keywords_any["calm"] and keywords_any["local pickup"]
    When I evaluate "calm but no pickup info here"
    Then the result is False
