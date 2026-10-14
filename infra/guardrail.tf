# Bedrock Guardrail used standalone (ApplyGuardrail): screens the incoming spec for prompt
# attacks and real-looking identifiers, and the generated docs for leaked identifiers.
resource "aws_bedrock_guardrail" "factory" {
  name                      = "${var.name}-guard"
  description               = "Agent factory input/output screening"
  blocked_input_messaging   = "Blocked by agent-factory guardrail (input)."
  blocked_outputs_messaging = "Blocked by agent-factory guardrail (output)."

  content_policy_config {
    filters_config {
      type            = "PROMPT_ATTACK"
      input_strength  = "HIGH"
      output_strength = "NONE"
    }
  }

  sensitive_information_policy_config {
    dynamic "pii_entities_config" {
      for_each = ["US_SOCIAL_SECURITY_NUMBER", "CREDIT_DEBIT_CARD_NUMBER", "US_BANK_ACCOUNT_NUMBER",
      "INTERNATIONAL_BANK_ACCOUNT_NUMBER", "UK_NATIONAL_HEALTH_SERVICE_NUMBER", "AWS_SECRET_KEY", "PASSWORD"]
      content {
        type   = pii_entities_config.value
        action = "BLOCK"
      }
    }
    # India identifiers have no built-in detector, so match them by pattern.
    regexes_config {
      name        = "aadhaar"
      description = "Aadhaar number (12 digits, first digit 2-9)"
      pattern     = "\\b[2-9][0-9]{3}[ -]?[0-9]{4}[ -]?[0-9]{4}\\b"
      action      = "BLOCK"
    }
    regexes_config {
      name        = "pan"
      description = "Indian PAN"
      pattern     = "\\b[A-Z]{5}[0-9]{4}[A-Z]\\b"
      action      = "BLOCK"
    }
  }
}

resource "aws_bedrock_guardrail_version" "factory" {
  guardrail_arn = aws_bedrock_guardrail.factory.guardrail_arn
  description   = "v1"
}
