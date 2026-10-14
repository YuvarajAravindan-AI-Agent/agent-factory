data "archive_file" "tasks" {
  type        = "zip"
  source_file = "${path.module}/../lambdas/tasks.py"
  output_path = "${path.module}/../build/tasks.zip"
}

data "archive_file" "approve" {
  type        = "zip"
  source_file = "${path.module}/../lambdas/approve.py"
  output_path = "${path.module}/../build/approve.zip"
}

data "aws_iam_policy_document" "lambda_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

# ---------------------------------------------------------------- tasks
resource "aws_iam_role" "tasks" {
  name               = "${var.name}-tasks"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

resource "aws_iam_role_policy_attachment" "tasks_logs" {
  role       = aws_iam_role.tasks.name
  policy_arn = "arn:${data.aws_partition.p.partition}:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "tasks" {
  role = aws_iam_role.tasks.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = "bedrock-agentcore:InvokeAgentRuntime",
      Resource = ["${aws_bedrockagentcore_agent_runtime.factory.agent_runtime_arn}", "${aws_bedrockagentcore_agent_runtime.factory.agent_runtime_arn}/*"] },
      { Effect = "Allow", Action = "bedrock:ApplyGuardrail", Resource = aws_bedrock_guardrail.factory.guardrail_arn },
      { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject"], Resource = ["${aws_s3_bucket.ws.arn}/runs/*", "${aws_s3_bucket.ws.arn}/deliverables/*", "${aws_s3_bucket.ws.arn}/codebuild-logs/*"] },
      { Effect = "Allow", Action = "codebuild:BatchGetBuilds", Resource = [aws_codebuild_project.deps.arn, aws_codebuild_project.test.arn] },
      { Effect = "Allow", Action = "sns:Publish", Resource = aws_sns_topic.approvals.arn },
    ]
  })
}

resource "aws_lambda_function" "tasks" {
  function_name    = "${var.name}-tasks"
  role             = aws_iam_role.tasks.arn
  runtime          = "python3.12"
  handler          = "tasks.handler"
  filename         = data.archive_file.tasks.output_path
  source_code_hash = data.archive_file.tasks.output_base64sha256
  timeout          = 120
  memory_size      = 256
  environment {
    variables = {
      WORKSPACE_BUCKET  = aws_s3_bucket.ws.bucket
      AGENT_RUNTIME_ARN = aws_bedrockagentcore_agent_runtime.factory.agent_runtime_arn
      GUARDRAIL_ID      = aws_bedrock_guardrail.factory.guardrail_id
      GUARDRAIL_VERSION = aws_bedrock_guardrail_version.factory.version
      TOPIC_ARN         = aws_sns_topic.approvals.arn
      APPROVAL_URL      = aws_lambda_function_url.approve.function_url
    }
  }
}

# ---------------------------------------------------------------- approve endpoint
resource "aws_iam_role" "approve" {
  name               = "${var.name}-approve"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

resource "aws_iam_role_policy_attachment" "approve_logs" {
  role       = aws_iam_role.approve.name
  policy_arn = "arn:${data.aws_partition.p.partition}:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "approve" {
  role = aws_iam_role.approve.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = ["states:SendTaskSuccess", "states:SendTaskFailure"], Resource = "*" }]
  })
}

resource "aws_lambda_function" "approve" {
  function_name    = "${var.name}-approve"
  role             = aws_iam_role.approve.arn
  runtime          = "python3.12"
  handler          = "approve.handler"
  filename         = data.archive_file.approve.output_path
  source_code_hash = data.archive_file.approve.output_base64sha256
  timeout          = 15
}

resource "aws_lambda_function_url" "approve" {
  function_name      = aws_lambda_function.approve.function_name
  authorization_type = "NONE"
}
