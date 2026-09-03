"""将开盘啦模型路由到独立的 kaipanla 数据库。"""

KAIPANLA_APP_LABEL = "kaipanla"
KAIPANLA_DB_ALIAS = "kaipanla"


class KaipanlaRouter:
    """只把 ``kaipanla`` app 的读写与迁移定向到独立数据库。"""

    def db_for_read(self, model, **hints):
        if model._meta.app_label == KAIPANLA_APP_LABEL:
            return KAIPANLA_DB_ALIAS
        return None

    def db_for_write(self, model, **hints):
        if model._meta.app_label == KAIPANLA_APP_LABEL:
            return KAIPANLA_DB_ALIAS
        return None

    def allow_relation(self, obj1, obj2, **hints):
        # 开盘啦与东财模型之间不建立跨库外键。
        if (
            obj1._meta.app_label == KAIPANLA_APP_LABEL
            or obj2._meta.app_label == KAIPANLA_APP_LABEL
        ):
            return obj1._meta.app_label == obj2._meta.app_label
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label == KAIPANLA_APP_LABEL:
            return db == KAIPANLA_DB_ALIAS
        if db == KAIPANLA_DB_ALIAS:
            # 独立库只承载开盘啦自己的表，其它 app 一律不落库。
            return False
        return None
