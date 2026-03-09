# -*- coding: utf-8 -*-
"""
单独测试 main.py 启动的 Flask 后端各个接口的情况
使用内置 urllib 以避免缺少 requests 依赖
"""

import urllib.request
import urllib.error
import urllib.parse
import json
import time

BASE_URL = "http://127.0.0.1:5001"
PASS = "✅"
FAIL = "❌"

def test_endpoint(name, method, path, expected_status=200):
    print(f"\n[测试] {name} -> {method} {path}")
    start_time = time.time()
    req = urllib.request.Request(f"{BASE_URL}{path}", method=method)
    
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status_code = resp.getcode()
            body = resp.read()
            elapsed = (time.time() - start_time) * 1000
            
            if status_code == expected_status:
                print(f"  {PASS} HTTP {status_code} ({elapsed:.0f}ms)")
                try:
                    data = json.loads(body.decode('utf-8'))
                    if isinstance(data, dict):
                        keys_to_print = {k: v for k, v in data.items() if k in ("msg", "success", "total", "count")}
                        if keys_to_print:
                            print(f"  返回摘要: {keys_to_print}")
                    return True, data
                except:
                    print(f"  响应内容非 JSON (长度: {len(body)})")
                    return True, body.decode('utf-8', errors='ignore')
            else:
                print(f"  {FAIL} HTTP {status_code} (Expected {expected_status}) ({elapsed:.0f}ms)")
                print(f"  错误详情: {body.decode('utf-8', errors='ignore')[:200]}")
                return False, None
                
    except urllib.error.HTTPError as e:
        elapsed = (time.time() - start_time) * 1000
        print(f"  {FAIL} HTTP {e.code} (Expected {expected_status}) ({elapsed:.0f}ms)")
        try:
            body = e.read().decode('utf-8')
            print(f"  错误详情: {body[:200]}")
        except:
            pass
        return False, None
    except urllib.error.URLError as e:
        print(f"  {FAIL} 连接失败，请确认后端服务 (main.py) 是否在 5001 端口启动。({e.reason})")
        return False, None
    except Exception as e:
        print(f"  {FAIL} 测试异常: {e}")
        return False, None


def main():
    print(f"=== 开始探测 U24Time Backend 接口 (Target: {BASE_URL}) ===")
    
    # 1. 健康检查
    ok, _ = test_endpoint("Service Health", "GET", "/health")
    if not ok:
        print("\n🚨 无法连接到服务器，测试终止。")
        return
        
    # 2. 调度器与数据源状态
    test_endpoint("Scheduler Status", "GET", "/api/v1/scheduler/status")
    test_endpoint("List All Sources", "GET", "/api/v1/sources")
    
    # 3. 页面聚合信息域
    test_endpoint("Domain List", "GET", "/api/v1/domains")
    test_endpoint("Domain Activity", "GET", "/api/v1/domains/activity")
    
    # 4. 数据获取
    test_endpoint("NewsFlash (无数据库缓存接口)", "GET", "/api/v1/newsflash?limit=5")
    test_endpoint("Items (分页获取库内文章)", "GET", "/api/v1/items?limit=5")
    
    # 5. 特定域下源的获取
    test_endpoint("Technology Domain Sources", "GET", "/api/v1/domains/technology/sources")
    
    # 6. Crawl Tasks 探活
    test_endpoint("Recent Crawl Tasks", "GET", "/api/v1/crawl/tasks")

    print("\n=== 测试完成 ===")

if __name__ == "__main__":
    main()
