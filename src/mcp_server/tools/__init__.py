"""
MCP Server Tools.

This package contains the MCP tool definitions exposed to clients.
All 12 tools are organized into 4 categories:
- RAG Core: query_knowledge_hub, list_collections, get_document_summary, ingest_documents
- Developer Tools: auto_coder, qa_tester, code_reviewer
- Project Management: setup, package, deploy
- Document Tools: resume_writer, doc_generator
"""

# === RAG Core Tools ===

from src.mcp_server.tools.query_knowledge_hub import (
    TOOL_NAME as QUERY_KNOWLEDGE_HUB_NAME,
    TOOL_DESCRIPTION as QUERY_KNOWLEDGE_HUB_DESCRIPTION,
    TOOL_INPUT_SCHEMA as QUERY_KNOWLEDGE_HUB_SCHEMA,
    QueryKnowledgeHubTool,
    query_knowledge_hub_handler,
    register_tool as register_query_knowledge_hub,
)

from src.mcp_server.tools.list_collections import (
    TOOL_NAME as LIST_COLLECTIONS_NAME,
    TOOL_DESCRIPTION as LIST_COLLECTIONS_DESCRIPTION,
    TOOL_INPUT_SCHEMA as LIST_COLLECTIONS_SCHEMA,
    ListCollectionsTool,
    register_tool as register_list_collections,
)

from src.mcp_server.tools.get_document_summary import (
    TOOL_NAME as GET_DOCUMENT_SUMMARY_NAME,
    TOOL_DESCRIPTION as GET_DOCUMENT_SUMMARY_DESCRIPTION,
    TOOL_INPUT_SCHEMA as GET_DOCUMENT_SUMMARY_SCHEMA,
    GetDocumentSummaryTool,
    register_tool as register_get_document_summary,
)

from src.mcp_server.tools.ingest_documents import (
    TOOL_NAME as INGEST_DOCUMENTS_NAME,
    TOOL_DESCRIPTION as INGEST_DOCUMENTS_DESCRIPTION,
    TOOL_INPUT_SCHEMA as INGEST_DOCUMENTS_SCHEMA,
    IngestDocumentsTool,
    register_tool as register_ingest_documents,
)

# === Developer Tools ===

from src.mcp_server.tools.auto_coder import (
    TOOL_NAME as AUTO_CODER_NAME,
    TOOL_DESCRIPTION as AUTO_CODER_DESCRIPTION,
    TOOL_INPUT_SCHEMA as AUTO_CODER_SCHEMA,
    AutoCoderTool,
    register_tool as register_auto_coder,
)

from src.mcp_server.tools.qa_tester import (
    TOOL_NAME as QA_TESTER_NAME,
    TOOL_DESCRIPTION as QA_TESTER_DESCRIPTION,
    TOOL_INPUT_SCHEMA as QA_TESTER_SCHEMA,
    QATesterTool,
    register_tool as register_qa_tester,
)

from src.mcp_server.tools.code_reviewer import (
    TOOL_NAME as CODE_REVIEWER_NAME,
    TOOL_DESCRIPTION as CODE_REVIEWER_DESCRIPTION,
    TOOL_INPUT_SCHEMA as CODE_REVIEWER_SCHEMA,
    CodeReviewerTool,
    register_tool as register_code_reviewer,
)

# === Project Management Tools ===

from src.mcp_server.tools.setup import (
    TOOL_NAME as SETUP_NAME,
    TOOL_DESCRIPTION as SETUP_DESCRIPTION,
    TOOL_INPUT_SCHEMA as SETUP_SCHEMA,
    SetupTool,
    register_tool as register_setup,
)

from src.mcp_server.tools.package import (
    TOOL_NAME as PACKAGE_NAME,
    TOOL_DESCRIPTION as PACKAGE_DESCRIPTION,
    TOOL_INPUT_SCHEMA as PACKAGE_SCHEMA,
    PackageTool,
    register_tool as register_package,
)

from src.mcp_server.tools.deploy import (
    TOOL_NAME as DEPLOY_NAME,
    TOOL_DESCRIPTION as DEPLOY_DESCRIPTION,
    TOOL_INPUT_SCHEMA as DEPLOY_SCHEMA,
    DeployTool,
    register_tool as register_deploy,
)

# === Document Tools ===

from src.mcp_server.tools.resume_writer import (
    TOOL_NAME as RESUME_WRITER_NAME,
    TOOL_DESCRIPTION as RESUME_WRITER_DESCRIPTION,
    TOOL_INPUT_SCHEMA as RESUME_WRITER_SCHEMA,
    ResumeWriterTool,
    register_tool as register_resume_writer,
)

from src.mcp_server.tools.doc_generator import (
    TOOL_NAME as DOC_GENERATOR_NAME,
    TOOL_DESCRIPTION as DOC_GENERATOR_DESCRIPTION,
    TOOL_INPUT_SCHEMA as DOC_GENERATOR_SCHEMA,
    DocGeneratorTool,
    register_tool as register_doc_generator,
)

__all__ = [
    # RAG Core Tools
    "QUERY_KNOWLEDGE_HUB_NAME",
    "QUERY_KNOWLEDGE_HUB_DESCRIPTION",
    "QUERY_KNOWLEDGE_HUB_SCHEMA",
    "QueryKnowledgeHubTool",
    "register_query_knowledge_hub",
    
    "LIST_COLLECTIONS_NAME",
    "LIST_COLLECTIONS_DESCRIPTION",
    "LIST_COLLECTIONS_SCHEMA",
    "ListCollectionsTool",
    "register_list_collections",
    
    "GET_DOCUMENT_SUMMARY_NAME",
    "GET_DOCUMENT_SUMMARY_DESCRIPTION",
    "GET_DOCUMENT_SUMMARY_SCHEMA",
    "GetDocumentSummaryTool",
    "register_get_document_summary",
    
    "INGEST_DOCUMENTS_NAME",
    "INGEST_DOCUMENTS_DESCRIPTION",
    "INGEST_DOCUMENTS_SCHEMA",
    "IngestDocumentsTool",
    "register_ingest_documents",
    
    # Developer Tools
    "AUTO_CODER_NAME",
    "AUTO_CODER_DESCRIPTION",
    "AUTO_CODER_SCHEMA",
    "AutoCoderTool",
    "register_auto_coder",
    
    "QA_TESTER_NAME",
    "QA_TESTER_DESCRIPTION",
    "QA_TESTER_SCHEMA",
    "QATesterTool",
    "register_qa_tester",
    
    "CODE_REVIEWER_NAME",
    "CODE_REVIEWER_DESCRIPTION",
    "CODE_REVIEWER_SCHEMA",
    "CodeReviewerTool",
    "register_code_reviewer",
    
    # Project Management Tools
    "SETUP_NAME",
    "SETUP_DESCRIPTION",
    "SETUP_SCHEMA",
    "SetupTool",
    "register_setup",
    
    "PACKAGE_NAME",
    "PACKAGE_DESCRIPTION",
    "PACKAGE_SCHEMA",
    "PackageTool",
    "register_package",
    
    "DEPLOY_NAME",
    "DEPLOY_DESCRIPTION",
    "DEPLOY_SCHEMA",
    "DeployTool",
    "register_deploy",
    
    # Document Tools
    "RESUME_WRITER_NAME",
    "RESUME_WRITER_DESCRIPTION",
    "RESUME_WRITER_SCHEMA",
    "ResumeWriterTool",
    "register_resume_writer",
    
    "DOC_GENERATOR_NAME",
    "DOC_GENERATOR_DESCRIPTION",
    "DOC_GENERATOR_SCHEMA",
    "DocGeneratorTool",
    "register_doc_generator",
]
