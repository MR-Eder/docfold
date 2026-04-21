{{/*
Expand the name of the chart.
*/}}
{{- define "docfold.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "docfold.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "docfold.labels" -}}
helm.sh/chart: {{ include "docfold.name" . }}-{{ .Chart.Version | replace "+" "_" }}
{{ include "docfold.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "docfold.selectorLabels" -}}
app.kubernetes.io/name: {{ include "docfold.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
API selector labels
*/}}
{{- define "docfold.api.selectorLabels" -}}
{{ include "docfold.selectorLabels" . }}
app.kubernetes.io/component: api
{{- end }}

{{/*
Worker selector labels
*/}}
{{- define "docfold.worker.selectorLabels" -}}
{{ include "docfold.selectorLabels" . }}
app.kubernetes.io/component: worker
{{- end }}

{{/*
Redis URL
*/}}
{{- define "docfold.redisUrl" -}}
{{- if .Values.redis.enabled }}
redis://{{ include "docfold.fullname" . }}-redis-master:6379
{{- else }}
{{- .Values.config.redisUrl }}
{{- end }}
{{- end }}
