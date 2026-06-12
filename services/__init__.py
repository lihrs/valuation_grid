"""
services - 业务服务层

将复杂业务逻辑从 app.py 路由层分离，提供可复用的服务接口。
"""
from .recommendation import get_recommendations, RecommendationFilter
