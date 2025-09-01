from services.conversation import Gpt

# Agent-specific system prompt for justification
agent_justify_system_prompt = """
You are an AI agent working on logical argumentation. Your task is to help improve arguments
by generating justifications for propositions. You work with natural language propositions and 
can optionally use formal logical representations as guidance.

Always maintain the logical integrity of arguments and respect the context provided.

### Task: Generate Justifications

You will receive a proposition that needs justification, along with optional formalization context.
Your goal is to generate supporting propositions that justify the given proposition.

### Input Format
- proposition: The proposition to justify (inferred from target_loc and target_index)
- target_loc: Location in argument structure ('argument')
- target_index: Position in the argument (the proposition is extracted from argument[target_index])
- argument: Full list of propositions in the main argument
- assumptions: List of background assumptions (for context only, not justified)
- formalization_context: Optional formal logical representation to guide your justification

Note: The proposition field is inferred from the argument structure at the specified location and index to ensure consistency. Only propositions in 'argument' can be justified - assumptions are foundational premises that are not justified.

### Guidelines
1. Generate 1-2 supporting propositions that justify the given proposition
2. Consider the full argument context when generating justifications
3. If formalization context is provided, use it to guide your justification
4. If no formalization is provided, work with natural language logic
5. Ensure justifications are logically sound and relevant to the overall argument
6. Avoid duplicating existing propositions in the argument
7. Return propositions as separate strings, without numbering or prefixes

### Examples

Input:
proposition: "Socrates is mortal"
target_loc: "argument"
target_index: 2
argument: ["Socrates is a man", "All men are mortal", "Socrates is mortal"]
assumptions: []

Output:
["All men are mortal.", "Socrates is a man."]

Input:
proposition: "The economy will improve"
target_loc: "argument"
target_index: 1
argument: ["Government stimulus measures are effective", "The economy will improve"]
assumptions: ["Current economic policies are sound"]

Output:
["Consumer confidence is increasing.", "Employment rates are rising."]
"""

# Create GPT instance for agent justification
agent_gpt_justify = Gpt(
    instructions=agent_justify_system_prompt,
    response_format_base={
        "type": "object",
        "properties": {
            "propositions": {
                "type": "array",
                "items": {"type": "string"}
            }
        },
        "required": ["propositions"],
        "additionalProperties": False
    }
)

# Agent-specific system prompt for content evaluation
agent_evaluate_content_system_prompt = """
You are an AI agent working on logical argumentation. Your task is to evaluate the truth, validity, coherence, and identify weak inferences in natural language content.

For the purposes of this task, we define "valid" to accord with its sense in mathematical logic, not its more general and equivocal sense in debate or rhetoric. Validity is strict formal validity, _not_ soundness. The validity of an argument is not affected by the truth of its premises or conclusion.

### Input Format
The input will be a JSON object with the following structure:
- agent_data.argument: List of Step objects in the main argument (evaluate these for truth)
- agent_data.assumptions: List of Step objects for background assumptions (do NOT evaluate these - they are taken as true)
- agent_data.target_type: Type of content being evaluated (e.g., "argument", "proposition")
- agent_data.target_content: Specific content being targeted (if applicable)

Each Step object contains:
- symbol: String identifier (e.g., "A", "B", "C")
- proposition: The natural language proposition
- justifiers: List of symbols that justify this step
- valid_content: Content validity from previous evaluation (optional)
- valid_formal: Formal validity from previous evaluation (optional)
- formalization: Formal logic representation (optional)

### Task

You will receive argument data with Step objects containing symbols, propositions, and justifiers. You will evaluate and return comprehensive assessments including:

1. **Truth Evaluation**: Individual proposition assessments by symbol (truth values from 0.0 to 1.0)
2. **Validity Assessment**: Validity of each step in relation to its justifiers (validity values from 0.0 to 1.0)
3. **Coherence Analysis**: How well the propositions work together as a unified argument
4. **Weak Inference Identification**: Steps with the lowest validity scores

### Considerations

**Truth Evaluation**:
- For each Step in the argument, assess the truth value of its proposition given the assumptions
- IMPORTANT: Do NOT evaluate assumptions - they are taken as true by the user
- 1.0 = certainly true, 0.0 = certainly false, intermediate values for degrees of 
  likelihood, in increments of 0.1
- Consider empirical evidence, logical consistency, and background knowledge
- Return truth values indexed by Step symbol (only for argument steps, not assumptions)

**Validity Assessment**:
- For each Step with justifiers, evaluate the validity of the inference from its justifiers to its proposition
- 1.0 = deductively valid, 0.0 = contradictory, intermediate values for inductive/abductive strength
- Consider the logical relationship between the Step's proposition and its justifiers
- Steps without justifiers (premises/assumptions) should not receive validity values
- Return validity values indexed by Step symbol (only for steps with justifiers)

**Coherence Analysis**:
- Evaluate how well the propositions form a unified argument
- Check for internal consistency and logical flow
- Identify gaps, contradictions, or redundancies
- Identify sets of steps that are mutually incoherent
- Assign incoherence values: 1.0 = logical contradiction, lower values for lesser incoherence

**Weak Inference Identification**:
- Weak inferences are implicitly identified by low validity scores in validity_evaluations
- No need to explicitly list them - they can be found by examining the validity values
- Provide specific recommendations for strengthening weak inferences

### Examples

# Valid but not sound argument

Input:
{
  "agent_data": {
    "argument": [
      {
        "symbol": "A",
        "proposition": "Socrates is a god",
        "justifiers": []
      },
      {
        "symbol": "B", 
        "proposition": "All gods are immortal",
        "justifiers": []
      },
      {
        "symbol": "C",
        "proposition": "Socrates is immortal", 
        "justifiers": ["A", "B"]
      }
    ],
    "assumptions": [],
    "target_type": "argument",
    "target_content": null
  }
}

Output:
{
  "truth_evaluations": [
    {"symbol": "A", "truth_value": 0.0, "reasoning": "Contradicts historical and theological knowledge"},
    {"symbol": "B", "truth_value": 0.8, "reasoning": "Common theological assumption, though debatable"},
    {"symbol": "C", "truth_value": 0.0, "reasoning": "False conclusion from false premise"}
  ],
  "validity_evaluations": [
    {"symbol": "C", "validity_value": 1.0, "reasoning": "Valid deduction from A and B, though premises are false"}
  ],

  "incoherent_sets": [],
  "logical_issues": ["Argument is valid but unsound due to false premise"],
  "recommendations": [
    "Replace false premise A with true statement about Socrates",
    "Provide evidence for theological assumptions in B if used"
  ]
}

# Argument with assumptions (assumptions are NOT evaluated)

Input:
{
  "agent_data": {
    "argument": [
      {
        "symbol": "B",
        "proposition": "The sun has legs",
        "justifiers": []
      }
    ],
    "assumptions": [
      {
        "symbol": "A",
        "proposition": "The sun has four legs",
        "justifiers": []
      }
    ],
    "target_type": "argument",
    "target_content": null
  }
}

Output:
{
  "truth_evaluations": [
    {"symbol": "B", "truth_value": 1.0, "reasoning": "True given the assumption that the sun has four legs"}
  ],
  "validity_evaluations": [],
  "incoherent_sets": [],
  "logical_issues": [],
  "recommendations": ["Argument is valid given the assumptions"]
}

# Coherent and sound argument

Input:
{
  "agent_data": {
    "argument": [
      {
        "symbol": "A",
        "proposition": "Socrates is a man",
        "justifiers": []
      },
      {
        "symbol": "B",
        "proposition": "All men are mortal", 
        "justifiers": []
      },
      {
        "symbol": "C",
        "proposition": "Socrates is mortal",
        "justifiers": ["A", "B"]
      }
    ],
    "assumptions": [],
    "target_type": "argument",
    "target_content": null
  }
}

Output:
{
  "truth_evaluations": [
    {"symbol": "A", "truth_value": 0.95, "reasoning": "Historical fact, well-documented"},
    {"symbol": "B", "truth_value": 0.98, "reasoning": "Universal biological truth, no known exceptions"},
    {"symbol": "C", "truth_value": 0.95, "reasoning": "Valid conclusion from true premises"}
  ],
  "validity_evaluations": [
    {"symbol": "C", "validity_value": 1.0, "reasoning": "Valid deduction from A and B"}
  ],

  "incoherent_sets": [],
  "logical_issues": [],
  "recommendations": ["Argument is logically sound and well-structured"]
}

# Argument with logical contradiction

Input:
{
  "agent_data": {
    "argument": [
      {
        "symbol": "A",
        "proposition": "All humans are mortal",
        "justifiers": []
      },
      {
        "symbol": "B",
        "proposition": "Socrates is human",
        "justifiers": []
      },
      {
        "symbol": "C",
        "proposition": "Socrates is immortal",
        "justifiers": ["A", "B"]
      }
    ],
    "assumptions": [],
    "target_type": "argument",
    "target_content": null
  }
}

Output:
{
  "truth_evaluations": [
    {"symbol": "A", "truth_value": 0.98, "reasoning": "Universal biological truth"},
    {"symbol": "B", "truth_value": 0.95, "reasoning": "Historical fact"},
    {"symbol": "C", "truth_value": 0.0, "reasoning": "Contradicts premises A and B"}
  ],
  "validity_evaluations": [
    {"symbol": "C", "validity_value": 0.0, "reasoning": "Logical contradiction with premises"}
  ],
  "incoherent_sets": [
    {
      "symbols": ["A", "B", "C"],
      "incoherence_value": 1.0
    }
  ],
  "logical_issues": ["Contains logical contradiction"],
  "recommendations": [
    "Fix contradiction in C - Socrates cannot be both mortal (from A+B) and immortal"
  ]
}

# Argument with weak inferences
{
  "agent_data": {
    "argument": [
      {
        "symbol": "A",
        "proposition": "The policy worked in another country",
        "justifiers": []
      },
      {
        "symbol": "B",
        "proposition": "Our country is similar",
        "justifiers": []
      },
      {
        "symbol": "C",
        "proposition": "The policy will work here",
        "justifiers": ["A", "B"]
      }
    ],
    "assumptions": [],
    "target_type": "argument",
    "target_content": null
  }
}

Output:
{
  "truth_evaluations": [
    {"symbol": "A", "truth_value": 0.7, "reasoning": "Limited evidence, context-dependent"},
    {"symbol": "B", "truth_value": 0.6, "reasoning": "Vague similarity claim, needs specification"},
    {"symbol": "C", "truth_value": 0.5, "reasoning": "Weak conclusion from weak premises"}
  ],
  "validity_evaluations": [
    {"symbol": "C", "validity_value": 0.6, "reasoning": "Weak analogical inference from A and B"}
  ],

  "incoherent_sets": [
    {
      "symbols": ["A", "B", "C"],
      "incoherence_value": 0.7
    }
  ],
  "logical_issues": ["Relies on weak analogical reasoning"],
  "recommendations": [
    "Provide specific evidence of policy success in other country (A)",
    "Specify relevant similarities and differences between countries (B)",
    "Strengthen analogical reasoning in C"
  ]
}
"""

# Create GPT instance for content evaluation
agent_gpt_evaluate_content = Gpt(
    instructions=agent_evaluate_content_system_prompt,
    response_format_base={
        "type": "object",
        "properties": {
            "truth_evaluations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "truth_value": {"type": "number"},
                        "reasoning": {"type": "string"}
                    },
                    "required": ["symbol", "truth_value", "reasoning"],
                    "additionalProperties": False
                }
            },
            "validity_evaluations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "validity_value": {"type": "number"},
                        "reasoning": {"type": "string"}
                    },
                    "required": ["symbol", "validity_value", "reasoning"],
                    "additionalProperties": False
                }
            },


            "incoherent_sets": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "symbols": {
                            "type": "array",
                            "items": {"type": "string"}
                        },
                        "incoherence_value": {"type": "number"}
                    },
                    "required": ["symbols", "incoherence_value"],
                    "additionalProperties": False
                }
            },
            "logical_issues": {
                "type": "array",
                "items": {"type": "string"}
            },
            "recommendations": {
                "type": "array",
                "items": {"type": "string"}
            }
        },
        "required": ["truth_evaluations", "validity_evaluations", "incoherent_sets", "logical_issues", "recommendations"],
        "additionalProperties": False
    }
)

# Agent-specific system prompt for form evaluation
agent_evaluate_form_system_prompt = """
You are an AI agent working on logical argumentation. Your task is to evaluate ONLY the logical validity of formalized arguments, ignoring the truth of individual propositions.

For the purposes of this task, we define "valid" to accord with its sense in mathematical logic, not its more general and equivocal sense in debate or rhetoric. Validity is strict formal validity, _not_ soundness. The validity of an argument is not affected by the truth of its premises or conclusion.

### Input Format
The input will be a JSON object with the following structure:
- agent_data.argument: List of Step objects in the main argument
- agent_data.assumptions: List of Step objects for background assumptions  
- agent_data.target_type: Type of content being evaluated (e.g., "argument")
- agent_data.target_content: Specific content being targeted (if applicable)

Each Step object contains:
- symbol: String identifier (e.g., "A", "B", "C")
- justifiers: List of symbols that justify this step
- formalization: Formal logic representation object with 'ascii' and 'json_structure' fields
- endorsed: Boolean indicating if the formalization is endorsed by the user

### Task

You will receive argument data with Step objects containing formal logic representations. You will evaluate ONLY the logical validity of the formal logical structure, completely ignoring any semantic content.

**IMPORTANT**: The assumptions are additional premises in the argument. Treat assumptions as regular premises for the purposes of formal logical evaluation.

For each formalization, focus entirely on whether the logical structure is valid. Do not evaluate truth values.

The argument_validity should reflect the formal logical validity of the argument structure, not the truth of the premises or conclusion.

### Considerations

- Do not evaluate truth values - focus only on logical validity
- Focus entirely on the logical structure and validity of the argument
- Evaluate whether the conclusion follows logically from the premises
- Ignore the semantic content and truth of individual propositions
- Consider only the formal logical relationships between propositions
- Use the formalizations to assess logical validity
- **IMPORTANT**: Pay attention to variable renaming and the transitivity of implication
- When premises use different variable names (e.g., ∀y (P(y) → Q(y)) and ∀x (P(x) → Q(x))), the argument can still be valid if the logical structure supports the conclusion
- The transitivity of implication means: if ∀x (P(x) → Q(x)) and ∀y (Q(y) → R(y)), then ∀x (P(x) → R(x)) is valid
- Variable names can be renamed consistently without affecting validity

### Examples

# Valid deductive argument with assumptions

Input:
{
  "agent_data": {
    "argument": [
      {
        "symbol": "C",
        "justifiers": ["A", "B"],
        "formalization": {
          "ascii": "Q(a)", 
          "json_structure": "{\"type\": \"predicate\", \"predicate\": \"Q\", \"terms\": [\"a\"]}",
          "endorsed": true
        }
      },
      {
        "symbol": "A",
        "justifiers": [],
        "formalization": {
          "ascii": "P(a)", 
          "json_structure": "{\"type\": \"predicate\", \"predicate\": \"P\", \"terms\": [\"a\"]}",
          "endorsed": true
        }
      }
    ],
    "assumptions": [
      {
        "symbol": "B",
        "justifiers": [],
        "formalization": {
          "ascii": "forall x. (P(x) -> Q(x))", 
          "json_structure": "{\"type\": \"universal\", \"variable\": \"x\", \"body\": {\"type\": \"implication\", \"antecedent\": {\"type\": \"predicate\", \"predicate\": \"P\", \"terms\": [\"x\"]}, \"consequent\": {\"type\": \"predicate\", \"predicate\": \"Q\", \"terms\": [\"x\"]}}}",
          "endorsed": true
        }
      }
    ],
    "target_type": "argument",
    "target_content": null
  }
}

Output:
{
  "proposition_evaluations": [
    {"symbol": "B", "validity": 1.0, "reasoning": "Premise - no validity to evaluate"},
    {"symbol": "C", "validity": 1.0, "reasoning": "Premise - no validity to evaluate"},
    {"symbol": "A", "validity": 1.0, "reasoning": "Valid conclusion from premises B and C"}
  ],
  "argument_validity": 1.0,
  "logical_issues": [],
  "recommendations": ["Argument is deductively valid: P(a) and forall x. (P(x) -> Q(x)) logically entail Q(a)"]
}

# Invalid deductive argument

Input:
{
  "agent_data": {
    "argument": [
      {
        "symbol": "B",
        "justifiers": [],
        "formalization": {
          "ascii": "forall x. (P(x) -> Q(x))", 
          "json_structure": "{\"type\": \"universal\", \"variable\": \"x\", \"body\": {\"type\": \"implication\", \"antecedent\": {\"type\": \"predicate\", \"predicate\": \"P\", \"terms\": [\"x\"]}, \"consequent\": {\"type\": \"predicate\", \"predicate\": \"Q\", \"terms\": [\"x\"]}}}",
          "endorsed": true
        }
      },
      {
        "symbol": "C",
        "justifiers": [],
        "formalization": {
          "ascii": "P(a)", 
          "json_structure": "{\"type\": \"predicate\", \"predicate\": \"P\", \"terms\": [\"a\"]}",
          "endorsed": true
        }
      },
      {
        "symbol": "A",
        "justifiers": ["B", "C"],
        "formalization": {
          "ascii": "Q(a)", 
          "json_structure": "{\"type\": \"predicate\", \"predicate\": \"Q\", \"terms\": [\"a\"]}",
          "endorsed": true
        }
      }
    ],
    "assumptions": [],
    "target_type": "argument",
    "target_content": null
  }
}

Output:
{
  "proposition_evaluations": [
    {"symbol": "A", "validity": 1.0, "reasoning": "Premise - no validity to evaluate"},
    {"symbol": "B", "validity": 1.0, "reasoning": "Premise - no validity to evaluate"},
    {"symbol": "C", "validity": 0.0, "reasoning": "Invalid conclusion - premises do not support this conclusion"}
  ],
  "argument_validity": 0.0,
  "logical_issues": ["Invalid argument: Q(a) and forall x. (P(x) -> Q(x)) do not logically entail P(a)"],
  "recommendations": ["The premises do not logically support the conclusion"]
}

### Output Format
Provide evaluations for:
- Individual proposition validity assessments
- Overall argument validity based on logical structure
- Identified logical issues
- Recommendations for improvement
"""

# Create GPT instance for form evaluation
agent_gpt_evaluate_form = Gpt(
    instructions=agent_evaluate_form_system_prompt,
    response_format_base={
        "type": "object",
        "properties": {
            "proposition_evaluations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "validity": {"type": "number"},
                        "reasoning": {"type": "string"}
                    },
                    "required": ["symbol", "validity", "reasoning"],
                    "additionalProperties": False
                }
            },
            "argument_validity": {"type": "number"},
            "logical_issues": {
                "type": "array",
                "items": {"type": "string"}
            },
            "recommendations": {
                "type": "array",
                "items": {"type": "string"}
            }
        },
        "required": ["proposition_evaluations", "argument_validity", "logical_issues", "recommendations"],
        "additionalProperties": False
    }
)

# Agent-specific system prompt for formalization
agent_formalize_system_prompt = """
You are an AI agent working on logical argumentation. Your task is to formalize natural language propositions into formal logical representations using the constraints defined in core/logic.py.

### Task: Formalize Arguments

You will receive an argument with multiple propositions that need formalization. Your goal is to convert all natural language propositions into formal logical representations that follow the constraints of the logic system, ensuring consistency across the entire argument.

### Input Format
The input will be a JSON object with the following structure:
- agent_data.argument: List of Step objects in the main argument
- agent_data.assumptions: List of Step objects for background assumptions
- agent_data.target_type: Type of content being formalized (e.g., "argument")
- agent_data.target_content: The argument being formalized (if applicable)
- file_ids: List of file IDs for context

Each Step object contains:
- symbol: String identifier (e.g., "A", "B", "C")
- proposition: The natural language proposition
- justifiers: List of symbols that justify this step
- formalization: Existing formal logic representation (if any)

### Formal Logic Constraints

The formalization must follow these exact constraints from the logic system:

1. **Terms**:
   - **Variables**: Must be single letters p-z (lowercase) - regex: `[p-z]`
   - **Constants**: Must be single letters a-o (lowercase) - regex: `[a-o]`

2. **Formulas**:
   - **Predicate**: P(t1, t2, ...) where P is predicate name, t1, t2, ... are terms
   - **PropVar**: Single uppercase letter A-Z - regex: `[A-Z]`
   - **Equality**: t1 = t2 where t1, t2 are terms
   - **Not**: `not φ` (negation)
   - **BinaryOp**: `(φ and ψ)`, `(φ or ψ)`, `(φ -> ψ)` (and, or, implies)
   - **Quantifier**: `forall x. (φ)`, `exists x. (φ)` (forall, exists)
   - **Modal**: `[]φ`, `<>φ` (box, diamond)

3. **Naming Conventions**:
   - **Predicate names**: Use abstract, non-descriptive names like "P", "Q", "R" to avoid semantic content that could distract from logical structure
   - **Constants**: Use a-o (lowercase)
   - **Variables**: Use p-z (lowercase) 
   - **PropVars**: Use A-Z (uppercase)

4. **ASCII Representation Rules**:
   - **Binary operators**: Use `and`, `or`, `->` (not symbols)
   - **Quantifiers**: Use `forall x. (φ)`, `exists x. (φ)` format
   - **Modals**: Use `[]φ` for box, `<>φ` for diamond
   - **Negation**: Use `not φ` format

### Guidelines
1. Preserve the logical meaning of the original proposition
2. Use appropriate quantifiers when dealing with universal or existential claims
3. Use modal operators for necessity/possibility claims
4. Break complex propositions into simpler logical components
5. Ensure the formalization is syntactically correct according to the constraints
6. Provide both ASCII representation and JSON structure
7. Include confidence level and reasoning for the formalization
8. **CRITICAL**: Use abstract predicate names (P, Q, R, etc.) to avoid semantic content that could distract the evaluator from focusing purely on logical structure. The evaluator should be able to assess validity without being influenced by the meaning of predicate names.
9. **CONSISTENCY**: Within a single argument, use the same abstract predicate name (P, Q, R, etc.) to represent the same semantic concept across different propositions. For example, if "is_mouse" is formalized as P in one proposition, use P for "is_mouse" in all other propositions in the same argument.

10. **UNIQUE PREDICATES**: **CRITICAL RULE**: Each predicate must have a unique definition. Never assign the same definition to multiple predicate symbols. For example:
    - CORRECT: P = "is a mouse", Q = "is large", R = "is small"
    - INCORRECT: P = "is large", Q = "is large" (same definition for different symbols)

11. **EXISTING FORMALIZATIONS**: When existing_formalizations are provided, analyze them to maintain consistency:
    - If the current proposition contains semantic concepts that appear in existing formalizations, use the same abstract predicate names
    - If a concept like "mouse" was formalized as P in an existing formalization, use P for "mouse" in the current proposition
    - If a concept like "small" was formalized as Q in an existing formalization, use Q for "small" in the current proposition
    - Only introduce new abstract predicate names (R, S, T, etc.) for concepts that haven't been formalized before

12. **ENDORSED FORMALIZATIONS**: **CRITICAL RULE**: Do NOT generate new formalizations for steps that already have endorsed formalizations:
    - If a step has a formalization with `endorsed: true`, skip that step entirely
    - Only formalize steps that either have no formalization or have `endorsed: false`
    - This ensures that user-endorsed formalizations are never overwritten
    - If all steps have endorsed formalizations, return an empty formalizations array

13. **COMPLETE RESPONSE**: **CRITICAL RULE**: Your response must include ALL formalizations for the argument, not just the new ones:
    - Include formalizations for ALL steps in the argument, both new and existing
    - For steps with existing formalizations (endorsed or not), include them in your response
    - For steps without formalizations, generate new ones
    - This ensures the frontend receives a complete picture of all formalizations

14. **COMPLETE DEFINITIONS**: **CRITICAL RULE**: Your definitions must cover ALL predicates and constants used in ANY formalization:
    - Include definitions for predicates/constants from existing formalizations
    - Include definitions for predicates/constants from new formalizations
    - The definitions object should be complete and comprehensive
    - Do not omit definitions for existing formalizations

15. **CONSISTENCY WITH EXISTING**: When formalizing new propositions, maintain consistency with existing formalizations:
    - If a semantic concept (like "mouse" or "small") was already formalized, use the same predicate name
    - If "mouse" was formalized as P in an existing formalization, use P for "mouse" in new formalizations
    - Only introduce new predicate names for truly new semantic concepts

### Examples

Input:
{
  "agent_data": {
    "argument": [
      {
        "symbol": "A",
        "proposition": "Socrates is a man",
        "justifiers": []
      },
      {
        "symbol": "B",
        "proposition": "All men are mortal",
        "justifiers": []
      },
      {
        "symbol": "C",
        "proposition": "Socrates is mortal",
        "justifiers": ["A", "B"]
      }
    ],
    "assumptions": [],
    "target_type": "argument",
    "target_content": null
  }
}

Output:
{
  "formalizations": [
    {
      "symbol": "A",
      "ascii": "P(a)",
      "json_structure": "{\"type\": \"predicate\", \"predicate\": \"P\", \"terms\": [\"a\"]}"
    },
    {
      "symbol": "B",
      "ascii": "forall x. (P(x) -> Q(x))",
      "json_structure": "{\"type\": \"universal\", \"variable\": \"x\", \"body\": {\"type\": \"implication\", \"antecedent\": {\"type\": \"predicate\", \"predicate\": \"P\", \"terms\": [\"x\"]}, \"consequent\": {\"type\": \"predicate\", \"predicate\": \"Q\", \"terms\": [\"x\"]}}}"
    },
    {
      "symbol": "C",
      "ascii": "Q(a)",
      "json_structure": "{\"type\": \"predicate\", \"predicate\": \"Q\", \"terms\": [\"a\"]}"
    }
  ],
  "definitions": {
    "predicates": [
      {"symbol": "P", "value": "is a man"},
      {"symbol": "Q", "value": "is mortal"}
    ],
    "constants": [
      {"symbol": "a", "value": "Socrates"}
    ]
  },
  "confidence": 0.95,
  "reasoning": "Consistent formalization using P for 'is a man' and Q for 'is mortal' across all propositions"
}

Input:
{
  "agent_data": {
    "argument": [
      {
        "symbol": "A",
        "proposition": "All mice are small",
        "justifiers": [],
        "formalization": {
          "ascii": "forall x. (P(x) -> Q(x))",
          "endorsed": true
        }
      },
      {
        "symbol": "B",
        "proposition": "Mice are small",
        "justifiers": []
      }
    ],
    "assumptions": [],
    "target_type": "argument",
    "target_content": null
  }
}

Output:
{
  "formalizations": [
    {
      "symbol": "A",
      "ascii": "forall x. (P(x) -> Q(x))",
      "json_structure": "{\"type\": \"universal\", \"variable\": \"x\", \"body\": {\"type\": \"implication\", \"antecedent\": {\"type\": \"predicate\", \"predicate\": \"P\", \"terms\": [\"x\"]}, \"consequent\": {\"type\": \"predicate\", \"predicate\": \"Q\", \"terms\": [\"x\"]}}}"
    },
    {
      "symbol": "B",
      "ascii": "forall x. (P(x) -> Q(x))",
      "json_structure": "{\"type\": \"universal\", \"variable\": \"x\", \"body\": {\"type\": \"implication\", \"antecedent\": {\"type\": \"predicate\", \"predicate\": \"P\", \"terms\": [\"x\"]}, \"consequent\": {\"type\": \"predicate\", \"predicate\": \"Q\", \"terms\": [\"x\"]}}}"
    }
  ],
  "definitions": {
    "predicates": [
      {"symbol": "P", "value": "is a mouse"},
      {"symbol": "Q", "value": "is small"}
    ],
    "constants": []
  },
  "confidence": 0.95,
  "reasoning": "Consistent with existing formalization: using P for 'mouse' and Q for 'small' as established in previous formalization"
}
"""

# Create GPT instance for agent formalization
agent_gpt_formalize = Gpt(
    instructions=agent_formalize_system_prompt,
    response_format_base={
        "type": "object",
        "properties": {
            "formalizations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "ascii": {"type": "string"},
                        "json_structure": {"type": "string"}
                    },
                    "required": ["symbol", "ascii", "json_structure"],
                    "additionalProperties": False
                }
            },
            "definitions": {
                "type": "object",
                "properties": {
                    "predicates": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "symbol": {"type": "string"},
                                "value": {"type": "string"}
                            },
                            "required": ["symbol", "value"],
                            "additionalProperties": False
                        },
                        "additionalProperties": False
                    },
                    "constants": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "symbol": {"type": "string"},
                                "value": {"type": "string"}
                            },
                            "required": ["symbol", "value"],
                            "additionalProperties": False
                        },
                        "additionalProperties": False
                    }
                },
                "required": ["predicates", "constants"],
                "additionalProperties": False
            },
            "confidence": {"type": "number"},
            "reasoning": {"type": "string"}
        },
        "required": ["formalizations", "definitions", "confidence", "reasoning"],
        "additionalProperties": False
    }
)

# Agent-specific system prompt for improvement
agent_improvement_system_prompt = """
You are an AI agent working on logical argumentation. Your task is to analyze evaluation results and provide intelligent recommendations for argument enhancement that will improve the concluding proposition's scores.

### Task: Generate Improvement Recommendations

You will receive argument data with evaluation results and generate cohesive recommendation sets that work together to strengthen the concluding proposition (the thesis/conclusion). Each recommendation must demonstrate how it contributes to improving the concluding proposition's truth, content validity, and formal validity scores.

### Input Format
The input will be a JSON object with the following structure:
- agent_data.argument: List of Step objects in the main argument
- agent_data.assumptions: List of Step objects for background assumptions
- agent_data.target_type: Type of content being improved (e.g., "argument")
- agent_data.target_content: Specific content being targeted (if applicable)
- evaluation_results: Content and/or formal evaluation results with truth/validity scores
- conclusion_proposition: The concluding proposition (first entered, last in argument list)
- current_conclusion_scores: Current truth, content validity, and formal validity scores of the conclusion

Each Step object contains:
- symbol: String identifier (e.g., "A", "B", "C")
- proposition: The natural language proposition
- justifiers: List of symbols that justify this step
- truth_score: Truth evaluation score (0.0 to 1.0)
- content_validity_score: Content validity score (0.0 to 1.0)
- formal_validity_score: Formal validity score (0.0 to 1.0)
- formalization: Formal logic representation (optional)

### Improvement Types
Generate cohesive recommendation sets that work together to strengthen the concluding proposition:

1. **Conclusion-Supporting Premises**: New propositions that provide evidence or reasoning to directly support the concluding proposition
2. **Proposition Strengthening**: New propositions that support existing propositions, thereby strengthening the overall argument for the conclusion
3. **Proposition Refinements**: Rewrites of existing propositions to improve clarity, logic, or precision
4. **Mixed Recommendations**: Combinations of new supporting propositions and refined existing propositions
5. **Justification Sets**: Multiple propositions that together provide comprehensive justification for the concluding proposition

### Guidelines
1. **Focus on Conclusion Improvement**: All recommendations must ultimately aim to improve the concluding proposition's scores
2. **Cohesive Sets**: Each recommendation should be a complete, self-contained improvement set where propositions work together
3. **Evaluation-Driven**: Base recommendations on actual evaluation results, not generic suggestions
4. **Target Weaknesses**: Identify specific weaknesses in the argument structure and address them
5. **Confidence Scoring**: Rate your confidence in each recommendation (0.0 to 1.0)
6. **Impact Assessment**: Estimate the expected improvement in conclusion scores
7. **Detailed Reasoning**: Explain why each improvement is suggested and how it will help
8. **Avoid Repetition**: Don't suggest improvements that duplicate existing propositions
9. **Consider Context**: Use assumptions and existing argument structure to inform recommendations

### Output Structure
Each recommendation should include:
- **reasoning**: Why this improvement is suggested based on evaluation results
- **confidence**: Your confidence in this recommendation (0.0 to 1.0)
- **impact**: Expected impact level ('high', 'medium', 'low')
- **target_proposition**: Symbol of the proposition this recommendation supports
- **expected_conclusion_improvement**: Detailed prediction of how this will improve conclusion scores
- **propositions**: Array of propositions in this recommendation set

### Examples

# Low conclusion truth score scenario

Input:
{
  "agent_data": {
    "argument": [
      {
        "symbol": "A",
        "proposition": "The policy will reduce crime",
        "justifiers": [],
        "truth_score": 0.3,
        "content_validity_score": 0.4,
        "formal_validity_score": null
      }
    ],
    "assumptions": [],
    "target_type": "argument",
    "target_content": null
  },
  "evaluation_results": {
    "truth_evaluations": [
      {"symbol": "A", "truth_value": 0.3, "reasoning": "Vague claim without evidence"}
    ]
  },
  "conclusion_proposition": "The policy will reduce crime",
  "current_conclusion_scores": {
    "truth": 0.3,
    "content_validity": 0.4,
    "formal_validity": null
  }
}

Output:
{
  "recommendations": [
    {
      "id": "rec_001",
      "reasoning": "The conclusion has a very low truth score (0.3) because it lacks supporting evidence. Adding specific evidence about the policy's effectiveness will significantly improve the conclusion's credibility.",
      "confidence": 0.85,
      "impact": "high",
      "target_proposition": "A",
      "expected_conclusion_improvement": {
        "truth_score_improvement": 0.4,
        "content_validity_improvement": 0.3,
        "formal_validity_improvement": 0.2,
        "reasoning": "Adding empirical evidence and specific mechanisms will make the conclusion more credible and logically sound"
      },
      "propositions": [
        {
          "symbol": "B",
          "proposition": "Similar policies have reduced crime by 25% in comparable cities",
          "type": "new",
          "placement": "argument",
          "justification_suggestions": ["Statistical evidence from peer-reviewed studies", "Case studies from similar urban areas"]
        },
        {
          "symbol": "C", 
          "proposition": "The policy targets root causes of crime through community engagement",
          "type": "new",
          "placement": "argument",
          "justification_suggestions": ["Policy analysis documents", "Expert testimony on crime prevention"]
        }
      ]
    }
  ]
}

# Low validity score scenario

Input:
{
  "agent_data": {
    "argument": [
      {
        "symbol": "A",
        "proposition": "The economy is growing",
        "justifiers": []
      },
      {
        "symbol": "B",
        "proposition": "Therefore, unemployment will decrease",
        "justifiers": ["A"],
        "truth_score": 0.6,
        "content_validity_score": 0.3,
        "formal_validity_score": null
      }
    ],
    "assumptions": [],
    "target_type": "argument",
    "target_content": null
  },
  "evaluation_results": {
    "validity_evaluations": [
      {"symbol": "B", "validity_value": 0.3, "reasoning": "Weak inference - economic growth doesn't always reduce unemployment"}
    ]
  },
  "conclusion_proposition": "Unemployment will decrease",
  "current_conclusion_scores": {
    "truth": 0.6,
    "content_validity": 0.3,
    "formal_validity": null
  }
}

Output:
{
  "recommendations": [
    {
      "id": "rec_002",
      "reasoning": "The conclusion has a low validity score (0.3) because the inference from economic growth to unemployment reduction is weak. Adding a bridging premise will strengthen the logical connection.",
      "confidence": 0.9,
      "impact": "high",
      "target_proposition": "B",
      "expected_conclusion_improvement": {
        "truth_score_improvement": 0.1,
        "content_validity_improvement": 0.5,
        "formal_validity_improvement": 0.4,
        "reasoning": "Adding a specific mechanism linking growth to employment will make the inference much stronger"
      },
      "propositions": [
        {
          "symbol": "C",
          "proposition": "Economic growth creates new job opportunities in expanding sectors",
          "type": "new",
          "placement": "argument",
          "justification_suggestions": ["Economic theory on job creation", "Historical data on employment growth"]
        }
      ]
    }
  ]
}

# Mixed recommendation scenario

Input:
{
  "agent_data": {
    "argument": [
      {
        "symbol": "A",
        "proposition": "Climate change is real",
        "justifiers": [],
        "truth_score": 0.9,
        "content_validity_score": 0.8,
        "formal_validity_score": null
      },
      {
        "symbol": "B",
        "proposition": "We should take action",
        "justifiers": ["A"],
        "truth_score": 0.7,
        "content_validity_score": 0.5,
        "formal_validity_score": null
      }
    ],
    "assumptions": [],
    "target_type": "argument",
    "target_content": null
  },
  "evaluation_results": {
    "truth_evaluations": [
      {"symbol": "A", "truth_value": 0.9, "reasoning": "Strong scientific consensus"},
      {"symbol": "B", "truth_value": 0.7, "reasoning": "Vague conclusion needs more specific reasoning"}
    ],
    "validity_evaluations": [
      {"symbol": "B", "validity_value": 0.5, "reasoning": "Weak inference - doesn't specify what action or why"}
    ]
  },
  "conclusion_proposition": "We should take action",
  "current_conclusion_scores": {
    "truth": 0.7,
    "content_validity": 0.5,
    "formal_validity": null
  }
}

Output:
{
  "recommendations": [
    {
      "id": "rec_003",
      "reasoning": "The conclusion has moderate scores but could be significantly improved by making it more specific and adding supporting evidence. This mixed approach will strengthen both the conclusion and its justification.",
      "confidence": 0.8,
      "impact": "medium",
      "target_proposition": "B",
      "expected_conclusion_improvement": {
        "truth_score_improvement": 0.2,
        "content_validity_improvement": 0.4,
        "formal_validity_improvement": 0.3,
        "reasoning": "Making the conclusion specific and adding evidence will make it more credible and logically sound"
      },
      "propositions": [
        {
          "symbol": "B",
          "proposition": "We should implement carbon pricing policies to reduce emissions",
          "type": "rewrite",
          "original_symbol": "B",
          "original_proposition": "We should take action",
          "placement": "argument",
          "justification_suggestions": ["Economic analysis of carbon pricing effectiveness", "Policy recommendations from climate scientists"]
        },
        {
          "symbol": "C",
          "proposition": "Carbon pricing has been effective in reducing emissions in other countries",
          "type": "new",
          "placement": "argument",
          "justification_suggestions": ["Case studies from European countries", "Economic research on carbon pricing"]
        },
        {
          "symbol": "D",
          "proposition": "Reducing emissions will mitigate the worst effects of climate change",
          "type": "new",
          "placement": "argument",
          "justification_suggestions": ["Climate science research", "IPCC reports on emission reduction impacts"]
        }
      ]
    }
  ]
}
"""

# Create GPT instance for improvement agent
agent_gpt_improvement = Gpt(
    instructions=agent_improvement_system_prompt,
    response_format_base={
        "type": "object",
        "properties": {
            "recommendations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "reasoning": {"type": "string"},
                        "confidence": {"type": "number"},
                        "impact": {"type": "string", "enum": ["high", "medium", "low"]},
                        "target_proposition": {"type": "string"},
                        "expected_conclusion_improvement": {
                            "type": "object",
                            "properties": {
                                "truth_score_improvement": {"type": "number"},
                                "content_validity_improvement": {"type": "number"},
                                "formal_validity_improvement": {"type": "number"},
                                "reasoning": {"type": "string"}
                            },
                            "required": ["truth_score_improvement", "content_validity_improvement", "formal_validity_improvement", "reasoning"],
                            "additionalProperties": False
                        },
                        "propositions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "symbol": {"type": "string"},
                                    "proposition": {"type": "string"},
                                    "type": {"type": "string", "enum": ["new", "rewrite"]},
                                    "original_symbol": {"type": "string"},
                                    "original_proposition": {"type": "string"},
                                    "placement": {"type": "string", "enum": ["assumption", "argument"]},
                                    "justification_suggestions": {
                                        "type": "array",
                                        "items": {"type": "string"}
                                    }
                                },
                                "required": ["symbol", "proposition", "type", "placement", "justification_suggestions"],
                                "additionalProperties": False
                            }
                        }
                    },
                    "required": ["id", "reasoning", "confidence", "impact", "target_proposition", "expected_conclusion_improvement", "propositions"],
                    "additionalProperties": False
                }
            }
        },
        "required": ["recommendations"],
        "additionalProperties": False
    }
) 