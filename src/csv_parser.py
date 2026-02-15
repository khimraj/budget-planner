"""
LLM-assisted CSV parser for bank/credit card statements.
Converts various CSV formats to internal format: Date, Description, Amount, Category
"""

import pandas as pd
import json
import logging
from openai import OpenAI
import os
from typing import Dict, List

logger = logging.getLogger(__name__)

# Fixed category list
CATEGORIES = [
    "Retail", "Travel", "Entertainment", "Food & Dining",
    "Utilities", "Health", "Income", "Transfer", "Other",
    "Groceries", "Education", "Subscription"
]


def parse_csv_with_llm(file_content: str) -> pd.DataFrame:
    """
    Parse CSV content using LLM to intelligently map columns to internal format.
    
    Args:
        file_content: Raw CSV content as string
        
    Returns:
        DataFrame with columns: Date, Description, Amount, Category
    """
    try:
        # First, try to read the CSV to understand its structure
        from io import StringIO
        df_raw = pd.read_csv(StringIO(file_content))
        
        logger.info(f"Raw CSV columns: {df_raw.columns.tolist()}")
        logger.info(f"Raw CSV shape: {df_raw.shape}")
        
        # Get sample rows for LLM analysis
        sample_rows = df_raw.head(5).to_dict('records')
        
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        # Create prompt for LLM to map columns
        prompt = f"""You are a financial data parser. Analyze this CSV data and map it to the required format.

**Input CSV Columns:** {df_raw.columns.tolist()}

**Sample Rows (first 5):**
{json.dumps(sample_rows, indent=2, default=str)}

**Required Output Format:**
- Date: Transaction date (convert to YYYY-MM-DD format)
- Description: Transaction description/merchant name
- Amount: Transaction amount as a number (positive for income/credits, negative for expenses/debits)
- Category: One of these categories only: {', '.join(CATEGORIES)}

**Instructions:**
1. Identify which columns map to Date, Description, and Amount
2. For each transaction, determine the appropriate Category from the list above
3. If there are separate Debit/Credit columns, combine them into Amount (credits positive, debits negative)
4. Categorize transactions based on description/merchant name
5. Return a JSON object with this structure:

{{
  "column_mapping": {{
    "date_column": "name_of_date_column",
    "description_column": "name_of_description_column",
    "amount_columns": {{"type": "single|debit_credit", "debit": "column_name", "credit": "column_name", "single": "column_name"}}
  }},
  "transactions": [
    {{
      "Date": "2024-01-15",
      "Description": "Amazon Purchase",
      "Amount": -50.00,
      "Category": "Retail"
    }}
  ]
}}

Parse ALL rows from the CSV, not just the sample.

CSV Data:
{file_content}"""

        response = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": "You are a financial data parser that converts CSV files to a standardized format. Always return valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0,
            response_format={"type": "json_object"}
        )
        
        result = json.loads(response.choices[0].message.content)
        logger.info(f"LLM parsing result: {json.dumps(result, indent=2)}")
        
        # Convert to DataFrame
        if "transactions" in result and result["transactions"]:
            df_parsed = pd.DataFrame(result["transactions"])
            
            # Ensure all required columns exist
            required_columns = ["Date", "Description", "Amount", "Category"]
            for col in required_columns:
                if col not in df_parsed.columns:
                    raise ValueError(f"Missing required column: {col}")
            
            # Validate categories
            invalid_categories = df_parsed[~df_parsed["Category"].isin(CATEGORIES)]["Category"].unique()
            if len(invalid_categories) > 0:
                logger.warning(f"Found invalid categories, mapping to 'Other': {invalid_categories}")
                df_parsed.loc[~df_parsed["Category"].isin(CATEGORIES), "Category"] = "Other"
            
            # Ensure Amount is numeric
            df_parsed["Amount"] = pd.to_numeric(df_parsed["Amount"], errors="coerce")
            
            # Ensure Date is in proper format
            df_parsed["Date"] = pd.to_datetime(df_parsed["Date"], errors="coerce").dt.strftime("%Y-%m-%d")
            
            logger.info(f"Successfully parsed {len(df_parsed)} transactions")
            return df_parsed[required_columns]
        else:
            raise ValueError("No transactions found in LLM response")
            
    except Exception as e:
        logger.error(f"Error parsing CSV with LLM: {e}")
        raise


def save_transactions(df: pd.DataFrame, output_path: str = "transactions.csv"):
    """
    Save parsed transactions to CSV file.
    
    Args:
        df: DataFrame with parsed transactions
        output_path: Path to save CSV file
    """
    df.to_csv(output_path, index=False)
    logger.info(f"Saved {len(df)} transactions to {output_path}")
