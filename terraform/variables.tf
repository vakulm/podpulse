variable "project_id" {
  description = "Google Cloud Project ID (e.g., vakul-100)"
  type        = string
  default     = "vakul-100"
}

variable "region" {
  description = "GCP Region for Vertex AI and Cloud Run"
  type        = string
  default     = "us-central1"
}

variable "flash_model" {
  description = "High-throughput Gemini Flash model"
  type        = string
  default     = "gemini-2.5-flash"
}

variable "pro_model" {
  description = "Deep-reasoning Gemini Pro model for fact-check arbitration"
  type        = string
  default     = "gemini-2.5-pro"
}

variable "container_image" {
  description = "Container image URI for PodPulse Cloud Run service"
  type        = string
  default     = "us-central1-docker.pkg.dev/vakul-100/podpulse/podpulse-agent:latest"
}
