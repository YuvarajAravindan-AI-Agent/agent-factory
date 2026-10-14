# AgentCore Runtime hosting the Strands harness agents (direct code deployment, no container).

resource "aws_s3_object" "agent_pkg" {
  bucket = aws_s3_bucket.ws.id
  key    = "artifacts/agent-${filemd5(var.agent_package)}.zip"
  source = var.agent_package
}

resource "aws_iam_role" "runtime" {
  name = "${var.name}-agent-runtime"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "bedrock-agentcore.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = {
        StringEquals = { "aws:SourceAccount" = local.acct }
        ArnLike      = { "aws:SourceArn" = "arn:${data.aws_partition.p.partition}:bedrock-agentcore:${var.region}:${local.acct}:*" }
      }
    }]
  })
}

resource "aws_iam_role_policy" "runtime" {
  role = aws_iam_role.runtime.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Sid = "Workspace", Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject"],
      Resource = "${aws_s3_bucket.ws.arn}/runs/*" },
      { Sid = "ListWorkspace", Effect = "Allow", Action = "s3:ListBucket", Resource = aws_s3_bucket.ws.arn },
      { Sid = "ReadPackage", Effect = "Allow", Action = "s3:GetObject", Resource = "${aws_s3_bucket.ws.arn}/artifacts/*" },
      { Sid = "GatewayToken", Effect = "Allow", Action = "secretsmanager:GetSecretValue",
      Resource = data.aws_secretsmanager_secret.gateway.arn },
      { Sid    = "ReportToWorkflow", Effect = "Allow",
        Action = ["states:SendTaskSuccess", "states:SendTaskFailure", "states:SendTaskHeartbeat"],
      Resource = "*" },
      { Sid = "Sandbox", Effect = "Allow",
        Action = ["bedrock-agentcore:StartCodeInterpreterSession", "bedrock-agentcore:InvokeCodeInterpreter",
        "bedrock-agentcore:StopCodeInterpreterSession", "bedrock-agentcore:GetCodeInterpreterSession"],
      Resource = "arn:${data.aws_partition.p.partition}:bedrock-agentcore:${var.region}:aws:code-interpreter/aws.codeinterpreter.v1" },
      { Sid = "Logs", Effect = "Allow",
        Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams",
        "logs:DescribeLogGroups"],
      Resource = "arn:${data.aws_partition.p.partition}:logs:${var.region}:${local.acct}:log-group:/aws/bedrock-agentcore/runtimes/*" },
      { Sid    = "Telemetry", Effect = "Allow",
        Action = ["xray:PutTraceSegments", "xray:PutTelemetryRecords", "cloudwatch:PutMetricData"],
      Resource = "*" },
    ]
  })
}

resource "aws_bedrockagentcore_agent_runtime" "factory" {
  agent_runtime_name = "agent_factory"
  description        = "Strands harness roles for the code factory"
  role_arn           = aws_iam_role.runtime.arn

  agent_runtime_artifact {
    code_configuration {
      entry_point = ["app.py"]
      runtime     = "PYTHON_3_12"
      code {
        s3 {
          bucket = aws_s3_bucket.ws.id
          prefix = aws_s3_object.agent_pkg.key
        }
      }
    }
  }

  network_configuration { network_mode = "PUBLIC" }

  lifecycle_configuration {
    idle_runtime_session_timeout = 900
    max_lifetime                 = 28800
  }

  environment_variables = {
    WORKSPACE_BUCKET     = aws_s3_bucket.ws.bucket
    GATEWAY_URL          = var.gateway_url
    GATEWAY_TOKEN_SECRET = var.gateway_token_secret
    MODEL_STRONG         = "gemini-4-argon"
    MODEL_FAST           = "gemini-3.8-flash"
  }

  depends_on = [aws_iam_role_policy.runtime]
}

output "agent_runtime_arn" { value = aws_bedrockagentcore_agent_runtime.factory.agent_runtime_arn }
