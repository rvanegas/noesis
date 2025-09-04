"""
Server startup initialization module.
This module initializes GPT instances and other resources at server startup
to avoid delays during the first API call.
"""

import asyncio
import threading
from core.utils import logger

def initialize_gpt_instances():
    """Initialize all GPT instances at server startup"""
    logger.info("Initializing GPT instances at server startup...")
    
    try:
        # Import and create GPT instances
        from services.agent_prompts import (
            agent_gpt_justify,
            agent_gpt_evaluate_content, 
            agent_gpt_evaluate_form,
            agent_gpt_formalize,
            agent_gpt_improvement
        )
        
        logger.info("GPT instances initialized successfully")
        
    except Exception as e:
        logger.error(f"Failed to initialize GPT instances: {e}")
        raise

def initialize_agent_coordinator():
    """Initialize the agent coordinator at server startup"""
    logger.info("Initializing agent coordinator at server startup...")
    
    try:
        from services.agent_coordinator import coordinator
        logger.info("Agent coordinator initialized successfully")
        
    except Exception as e:
        logger.error(f"Failed to initialize agent coordinator: {e}")
        raise

def run_startup_initialization():
    """Run all startup initialization in a background thread"""
    def init_worker():
        try:
            initialize_gpt_instances()
            initialize_agent_coordinator()
            logger.info("All startup initialization completed successfully")
        except Exception as e:
            logger.error(f"Startup initialization failed: {e}")
    
    # Run initialization in background thread to not block server startup
    init_thread = threading.Thread(target=init_worker, name="startup_init")
    init_thread.daemon = True
    init_thread.start()
    
    return init_thread
