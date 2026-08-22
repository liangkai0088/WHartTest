import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ('projects', '__first__'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='PerfTestScenario',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200, verbose_name='场景名称')),
                ('description', models.TextField(blank=True, verbose_name='场景描述')),
                ('source', models.CharField(choices=[('interface', '接口定义'), ('swagger', 'Swagger/OpenAPI'), ('har', 'HAR 文件'), ('ai', 'AI 编排')], default='interface', max_length=20, verbose_name='来源')),
                ('locustfile', models.TextField(blank=True, help_text='请求模板渲染出的 locustfile 字符串缓存', verbose_name='Locust 脚本缓存')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='perf_test_scenarios_created', to=settings.AUTH_USER_MODEL, verbose_name='创建人')),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='perf_test_scenarios', to='projects.project', verbose_name='所属项目')),
            ],
            options={
                'verbose_name': '性能测试场景',
                'verbose_name_plural': '性能测试场景',
                'ordering': ['-created_at'],
                'unique_together': {('name', 'project')},
                'indexes': [
                    models.Index(fields=['project', 'created_at'], name='perf_scenario_proj_created_idx'),
                ],
            },
        ),
        migrations.CreateModel(
            name='PerfTestRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200, verbose_name='请求名称')),
                ('method', models.CharField(choices=[('GET', 'GET'), ('POST', 'POST'), ('PUT', 'PUT'), ('DELETE', 'DELETE'), ('PATCH', 'PATCH'), ('HEAD', 'HEAD'), ('OPTIONS', 'OPTIONS')], default='GET', max_length=10, verbose_name='HTTP 方法')),
                ('url', models.TextField(blank=True, verbose_name='URL')),
                ('headers', models.JSONField(blank=True, default=dict, verbose_name='请求头')),
                ('params', models.JSONField(blank=True, default=dict, verbose_name='查询参数')),
                ('body', models.JSONField(blank=True, default=dict, verbose_name='请求体')),
                ('variables', models.JSONField(blank=True, default=dict, verbose_name='动态参数')),
                ('validators', models.JSONField(blank=True, default=list, verbose_name='断言规则')),
                ('weight', models.IntegerField(default=1, verbose_name='权重')),
                ('order', models.IntegerField(default=0, verbose_name='顺序')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('scenario', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='requests', to='perf_test.perftestscenario', verbose_name='所属场景')),
            ],
            options={
                'verbose_name': '压测请求模板',
                'verbose_name_plural': '压测请求模板',
                'ordering': ['order', 'id'],
                'indexes': [
                    models.Index(fields=['scenario', 'order'], name='perf_req_scenario_order_idx'),
                ],
            },
        ),
        migrations.CreateModel(
            name='PerfTestPlan',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('users', models.IntegerField(default=10, verbose_name='并发用户数')),
                ('spawn_rate', models.IntegerField(default=1, verbose_name='每秒启动用户数')),
                ('duration', models.IntegerField(default=60, verbose_name='持续时间(秒)')),
                ('think_time', models.FloatField(default=0, verbose_name='思考时间(秒)')),
                ('target_qps', models.IntegerField(blank=True, help_text='可选，预留字段，限流在后续版本增强', null=True, verbose_name='目标 QPS')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
                ('scenario', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='plan', to='perf_test.perftestscenario', verbose_name='所属场景')),
            ],
            options={
                'verbose_name': '压测负载模型',
                'verbose_name_plural': '压测负载模型',
            },
        ),
        migrations.CreateModel(
            name='PerfTestExecution',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('plan_snapshot', models.JSONField(blank=True, default=dict, verbose_name='负载参数快照')),
                ('status', models.CharField(choices=[('pending', '待执行'), ('running', '执行中'), ('completed', '已完成'), ('failed', '失败'), ('canceled', '已取消')], default='pending', max_length=20, verbose_name='状态')),
                ('progress', models.FloatField(default=0, verbose_name='进度(%)')),
                ('celery_task_id', models.CharField(blank=True, max_length=100, verbose_name='Celery 任务 ID')),
                ('error_message', models.TextField(blank=True, verbose_name='错误信息')),
                ('started_at', models.DateTimeField(blank=True, null=True, verbose_name='开始时间')),
                ('finished_at', models.DateTimeField(blank=True, null=True, verbose_name='结束时间')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('executed_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='perf_test_executions', to=settings.AUTH_USER_MODEL, verbose_name='执行人')),
                ('scenario', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='executions', to='perf_test.perftestscenario', verbose_name='所属场景')),
            ],
            options={
                'verbose_name': '压测执行记录',
                'verbose_name_plural': '压测执行记录',
                'ordering': ['-created_at'],
                'indexes': [
                    models.Index(fields=['scenario', 'created_at'], name='perf_exec_scenario_created_idx'),
                ],
            },
        ),
        migrations.CreateModel(
            name='PerfTestReport',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('total_requests', models.IntegerField(default=0, verbose_name='总请求数')),
                ('total_failures', models.IntegerField(default=0, verbose_name='失败请求数')),
                ('error_rate', models.FloatField(default=0, verbose_name='错误率(%)')),
                ('avg_response_time', models.FloatField(default=0, verbose_name='平均响应时间(ms)')),
                ('min_response_time', models.FloatField(default=0, verbose_name='最小响应时间(ms)')),
                ('max_response_time', models.FloatField(default=0, verbose_name='最大响应时间(ms)')),
                ('p50', models.FloatField(default=0, verbose_name='P50(ms)')),
                ('p95', models.FloatField(default=0, verbose_name='P95(ms)')),
                ('p99', models.FloatField(default=0, verbose_name='P99(ms)')),
                ('total_rps', models.FloatField(default=0, verbose_name='平均 RPS')),
                ('peak_rps', models.FloatField(default=0, verbose_name='峰值 RPS')),
                ('rps_series', models.JSONField(blank=True, default=list, verbose_name='RPS 时序')),
                ('bottleneck_summary', models.JSONField(blank=True, default=dict, verbose_name='瓶颈快照')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('execution', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='report', to='perf_test.perftestexecution', verbose_name='关联执行')),
            ],
            options={
                'verbose_name': '压测报告',
                'verbose_name_plural': '压测报告',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='PerfTestNode',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200, verbose_name='节点名称')),
                ('host', models.CharField(max_length=200, verbose_name='节点地址')),
                ('status', models.CharField(choices=[('online', '在线'), ('offline', '离线')], default='online', max_length=20, verbose_name='状态')),
                ('cpu_usage', models.FloatField(default=0, verbose_name='CPU 使用率(%)')),
                ('memory_usage', models.FloatField(default=0, verbose_name='内存使用率(%)')),
                ('last_heartbeat', models.DateTimeField(blank=True, null=True, verbose_name='最后心跳时间')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
            ],
            options={
                'verbose_name': '压测节点',
                'verbose_name_plural': '压测节点',
                'ordering': ['-created_at'],
            },
        ),
    ]
