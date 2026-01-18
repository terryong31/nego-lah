from connector import admin_supabase
from typing import List, Dict, Optional


def get_all_transactions() -> List[Dict]:
    """Get all transactions, newest first."""
    response = admin_supabase.table('transactions').select('*').order('created_at', desc=True).execute()
    return response.data


def get_transaction_by_item(item_id: str) -> Optional[Dict]:
    """Get transaction for a specific item."""
    response = admin_supabase.table('transactions').select('*').eq('item_id', item_id).execute()
    return response.data[0] if response.data else None


def get_transactions_by_status(status: str) -> List[Dict]:
    """Get transactions by status (completed, refunded, pending)."""
    response = admin_supabase.table('transactions').select('*').eq('status', status).execute()
    return response.data


def get_sales_summary() -> Dict:
    """
    Get summary stats for your sales.
    
    Returns:
        - total_sales: Total revenue
        - total_transactions: Number of completed sales
        - average_sale: Average sale price
        - refunded_amount: Total refunded
    """
    # Get completed transactions
    completed = admin_supabase.table('transactions').select('*').eq('status', 'completed').execute()
    completed_data = completed.data or []
    
    # Get refunded transactions
    refunded = admin_supabase.table('transactions').select('*').eq('status', 'refunded').execute()
    refunded_data = refunded.data or []
    
    total_sales = sum(float(t.get('amount', 0)) for t in completed_data)
    total_count = len(completed_data)
    refunded_amount = sum(float(t.get('amount', 0)) for t in refunded_data)
    
    return {
        'total_sales': total_sales,
        'total_transactions': total_count,
        'average_sale': round(total_sales / total_count, 2) if total_count > 0 else 0,
        'refunded_amount': refunded_amount,
        'refund_count': len(refunded_data)
    }
