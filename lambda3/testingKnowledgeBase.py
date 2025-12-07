import boto3
import os
import logging
from typing import List, Dict

logger = logging.getLogger()

AWS_REGION = os.environ.get("AWS_REGION", "us-east-2")
KNOWLEDGE_BASE_ID = os.environ["KNOWLEDGE_BASE_ID"]

kb_rt = boto3.client("bedrock-agent-runtime", region_name=AWS_REGION)


def retrieve_policy(cpt_codes: List[Dict] = None) -> List[Dict]:
    """
    Retrieve relevant policy clauses from Bedrock Knowledge Base.
    
    Args:
        plan_id: Insurance plan identifier
        cpt_codes: Optional list of CPT procedure codes
        
    Returns:
        List of retrieval results with policy snippets
    """
    try:
        # Build comprehensive query including CPT codes if available
        # If no codes, just return empty
        if not cpt_codes:
            logger.warning("No CPT codes provided to retrieve_policy; skipping KB retrieval.")
            return []

        query_parts = [
            f"For insurance plan, what policy sections describe coverage, limitations, or exclusions"
        ]
        
        # if icd_codes:
        #     query_parts.append(f"for diagnoses {', '.join(icd_codes)}")
        
        if cpt_codes:
            cpt_code_list = [c.get('code', '') for c in cpt_codes if c.get('code')]
            if cpt_code_list:
                query_parts.append(f"and procedures {', '.join(cpt_code_list[:10])}")  # Limit to first 10
        
        query_text = " ".join(query_parts) + "?"
        
        logger.info(f"KB query: {query_text}")
        
        # Call Bedrock Knowledge Base retrieve API
        response = kb_rt.retrieve(
            knowledgeBaseId=KNOWLEDGE_BASE_ID,
            retrievalQuery={"text": query_text},
            retrievalConfiguration={
                "vectorSearchConfiguration": {
                    "numberOfResults": 5  # top-K results
                }
            }
        )
        
        results = response.get("retrievalResults", [])
        logger.info(f"KB returned {len(results)} policy snippets")
        
        # Log snippet sources for debugging
        for i, result in enumerate(results, 1):
            score = result.get("score", 0)
            source = result.get("location", {}).get("s3Location", {}).get("uri", "unknown")
            logger.info(f"Snippet {i} - Score: {score:.3f}, Source: {source}")
        
        return results
        
    except Exception as e:
        logger.error(f"Error retrieving from Knowledge Base: {e}")
        return []


def format_snippets(snippets: List[Dict]) -> str:
    """
    Format retrieved policy snippets into a readable context string.
    
    Args:
        snippets: List of retrieval results from Knowledge Base
        
    Returns:
        Formatted string with all policy snippets
    """
    if not snippets:
        return "NO_POLICY_SNIPPETS_FOUND"
    
    parts = []
    for i, snippet in enumerate(snippets, start=1):
        # Extract text content
        text = snippet.get("content", {}).get("text", "")
        
        # Extract source location
        location = snippet.get("location", {})
        s3_location = location.get("s3Location", {})
        source_uri = s3_location.get("uri", "unknown")
        
        # Extract relevance score if available
        score = snippet.get("score", 0)
        
        # Format snippet with metadata
        part = f"[Policy Snippet {i}] (Relevance: {score:.3f})\n"
        part += f"Source: {source_uri}\n"
        part += f"Content:\n{text}\n"
        
        parts.append(part)
    
    formatted = "\n" + "="*80 + "\n"
    formatted += "\n".join(parts)
    formatted += "="*80 + "\n"
    
    return formatted
