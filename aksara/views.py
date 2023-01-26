from django.http import JsonResponse
from rest_framework import status, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from django.core.cache import cache
from django.conf import settings
from django.core.cache.backends.base import DEFAULT_TIMEOUT
from functools import reduce
from django.db.models import Q

from aksara.utils import cron_utils, triggers
from aksara.serializers import MetaSerializer, DashboardSerializer, CatalogSerializer
from aksara.models import MetaJson, DashboardJson, CatalogJson
from aksara.api_handling import handle, cache_search

from threading import Thread

import json
import os
import environ

env = environ.Env()
environ.Env.read_env()

"""
Endpoint for all single charts
"""


class CHART(APIView):
    def get(self, request, format=None):
        param_list = dict(request.GET)
        params_req = ["dashboard", "chart_name"]

        if all(p in param_list for p in params_req):
            dbd_name = param_list["dashboard"][0]
            chart_name = param_list["chart_name"][0]

            meta = MetaJson.objects.filter(dashboard_name=dbd_name).values(
                "dashboard_meta"
            )[0]["dashboard_meta"]
            api_params = meta["charts"][chart_name]["api_params"]
            chart_type = meta["charts"][chart_name]["chart_type"]
            api_type = meta["charts"][chart_name]["api_type"]
            chart_variables = meta["charts"][chart_name]["variables"]

            chart_data = DashboardJson.objects.filter(
                dashboard_name=dbd_name, chart_name=chart_name
            ).values("chart_data")[0]["chart_data"]

            data_as_of = chart_data["data_as_of"]
            chart_data = chart_data["data"]

            #  TEMP FIX
            temp = {}
            if chart_type == "timeseries_shared":
                const_keys = list(chart_variables["constant"].keys())
                for k in const_keys:
                    temp[k] = chart_data[k]

            for api in api_params:
                if api in param_list:
                    chart_data = chart_data[param_list[api][0]]
                else:
                    return JsonResponse({}, safe=False)

            if temp:
                chart_data.update(temp)

            overall_data = {}
            overall_data["data"] = chart_data
            overall_data["data_as_of"] = data_as_of

        return JsonResponse(overall_data, safe=False)


class UPDATE(APIView):
    def post(self, request, format=None):
        if is_valid_request(request, os.getenv("WORKFLOW_TOKEN")):
            thread = Thread(target=cron_utils.selective_update)
            thread.start()
            return Response(status=status.HTTP_200_OK)
        return JsonResponse({"status": 401, "message": "unauthorized"}, status=401)


class DASHBOARD(APIView):
    def get(self, request, format=None):
        if not is_valid_request(request, os.getenv("WORKFLOW_TOKEN")):
            return JsonResponse({"status": 401, "message": "unauthorized"}, status=401)

        param_list = dict(request.GET)
        params_req = ["dashboard"]

        if all(p in param_list for p in params_req):
            res = handle_request(param_list)
            res = handle.dashboard_additional_handling(param_list, res)
            return JsonResponse(res, safe=False)
        else:
            return JsonResponse({}, safe=False)


class DATA_VARIABLE(APIView):
    def get(self, request, format=None):
        if not is_valid_request(request, os.getenv("WORKFLOW_TOKEN")):
            return JsonResponse({"status": 401, "message": "unauthorized"}, status=401)

        param_list = dict(request.GET)
        params_req = ["id"]

        if all(p in param_list for p in params_req):
            res = data_variable_handler(param_list)
            return JsonResponse(res, safe=False)
        else:
            return JsonResponse({}, safe=False)


class DATA_CATALOG(APIView):
    def get(self, request, format=None):
        if not is_valid_request(request, os.getenv("WORKFLOW_TOKEN")):
            return JsonResponse({"status": 401, "message": "unauthorized"}, status=401)

        param_list = dict(request.GET)
        filters = get_filters_applied(param_list)
        info = ""

        if len(filters) > 0:
            # search_cache = cache.get("search_cache")
            # filter_list = cache_search.filter_options(param_list)
            # info = cache_search.filter_cache(filter_list, search_cache)

            info = CatalogJson.objects.filter(filters).values(
                "id",
                "catalog_name",
                "catalog_category",
                "catalog_category_name",
                "catalog_subcategory_name",
            )
        else:
            catalog_list = cache.get("catalog_list")

            if catalog_list:
                info = catalog_list
            else:
                info = list(
                    CatalogJson.objects.all().values(
                        "id",
                        "catalog_name",
                        "catalog_category",
                        "catalog_category_name",
                        "catalog_subcategory_name",
                    )
                )
                cache.set("catalog_list", info)

        res = {}
        res["total_all"] = len(info)
        if cache.get("source_filters"):
            res["source_filters"] = cache.get("source_filters")
        else:
            source_filters = cron_utils.source_filters_cache()
            res["source_filters"] = source_filters
            cache.set("source_filters", source_filters)
        # res["source_filters"] = cache.get('source_filters') if cache.get('source_filters') else cron_utils.source_filters_cache()

        res["dataset"] = {}

        lang = request.query_params.get("lang", "en")
        lang_mapping = {"en": 0, "bm": 1}

        if lang not in lang_mapping:
            lang = "en"

        for item in info:
            category = item["catalog_category_name"].split(" | ")[lang_mapping[lang]]
            sub_category = item["catalog_subcategory_name"].split(" | ")[
                lang_mapping[lang]
            ]

            obj = {}
            obj["catalog_name"] = item["catalog_name"].split(" | ")[lang_mapping[lang]]
            obj["id"] = item["id"]

            if category not in res["dataset"]:
                res["dataset"][category] = {}
                res["dataset"][category][sub_category] = [obj]
            else:
                if sub_category in res["dataset"][category]:
                    res["dataset"][category][sub_category].append(obj)
                else:
                    res["dataset"][category][sub_category] = [obj]

        return JsonResponse(res, safe=False)


"""
Checks which filters have been applied for the data-catalog
"""


def get_filters_applied(param_list):
    default_params = {
        "period": "",
        "geographic": [],
        "begin": "",
        "end": "",
        "source": [],
        "search": "",
    }

    for k, v in default_params.items():
        if k in param_list:
            if isinstance(v, str):
                default_params[k] = param_list[k][0]
            else:
                default_params[k] = param_list[k][0].split(",")

    # Check if parameters have been set, remove those which have not
    default_params = {k: v for k, v in default_params.items() if v}

    query = Q()

    for k, v in default_params.items():
        if k == "period":
            query &= Q(time_range=v)
        elif k == "geographic":
            for i in v:
                query |= Q(geographic__contains=i)
        elif k == "source":
            query &= Q(data_source__in=tuple(v))
        elif k == "search":
            query &= Q(catalog_name__icontains=v)
        if k == "begin":
            query &= Q(dataset_begin__lte=v)
        if k == "end":
            query &= Q(dataset_end__gte=v)

    return query


"""
Handles the data-variable queries, by chart applied
"""


def data_variable_chart_handler(data, chart_type, param_list):
    if chart_type == "TIMESERIES":
        filter = ""
        range = ""

        for i in data["API"]["filters"]:
            if i["key"] == "filter":
                filter = i["default"]["value"]
            elif i["key"] == "range":
                range = i["default"]["value"]

        if "filter" in param_list:
            filter = param_list["filter"][0]

        if "range" in param_list:
            range = param_list["range"][0]

        table_data = {}

        if filter:
            table_data["columns"] = data["chart_details"]["chart"][filter]["TABLE"][
                "columns"
            ]
            table_data["data"] = data["chart_details"]["chart"][filter]["TABLE"][
                "data"
            ][range]
            chart_data = data["chart_details"]["chart"][filter][range]
            intro = data["chart_details"]["intro"]
        else:
            table_data["columns"] = data["chart_details"]["chart"]["TABLE"]["columns"]
            table_data["data"] = data["chart_details"]["chart"]["TABLE"]["data"][range]
            chart_data = data["chart_details"]["chart"][range]
            intro = data["chart_details"]["intro"]

        return {"chart_data": chart_data, "table_data": table_data, "intro": intro}
    elif chart_type == "CHOROPLETH":
        if "filters" not in data["API"]:
            table_data = {}
            table_data["columns"] = data["chart_details"]["chart"]["TABLE"]["columns"]
            table_data["data"] = data["chart_details"]["chart"]["TABLE"]["data"]
            chart_data = data["chart_details"]["chart"]["CHART"]
            intro = data["chart_details"]["intro"]
            return {"chart_data": chart_data, "table_data": table_data, "intro": intro}
    elif chart_type == "TABLE":
        intro = data["chart_details"]["intro"]
        return {"table_data": data["chart_details"]["chart"], "intro": intro}
    elif chart_type == "GEOJSON":
        intro = data["chart_details"]["intro"]
        return {"intro": intro}
    elif chart_type == "BAR" or chart_type == "HBAR":
        defaults_api = {}

        for d in data["API"]["filters"]:
            defaults_api[d["key"]] = d["default"]["value"]

        intro = data["chart_details"]["intro"]  # Get intro
        tbl = data["chart_details"]["chart"]["table_data"]  # Get tbl data
        chart = data["chart_details"]["chart"]["chart_data"]  # Get chart data

        for k, v in defaults_api.items():
            if k in param_list:
                key = param_list[k][0]
                tbl = tbl[key]
                chart = chart[key]
            else:
                tbl = tbl[v]
                chart = chart[v]

        res = {"chart_data": chart, "table_data": tbl, "intro": intro}

        return res


"""
General handler for data-variables
"""


def data_variable_handler(param_list):
    var_id = param_list["id"][0]
    info = cache.get(var_id)

    if not info:
        info = CatalogJson.objects.filter(id=var_id).values("catalog_data")
        info = info[0]["catalog_data"]
        cache.set(var_id, info)

    chart_type = info["API"]["chart_type"]

    info["chart_details"] = data_variable_chart_handler(info, chart_type, param_list)

    if len(info) == 0:
        return {}
    return info


"""
Handles request for dashboards
"""


def handle_request(param_list):
    dbd_name = str(param_list["dashboard"][0])
    dbd_info = cache.get("META_" + dbd_name)

    if not dbd_info:
        dbd_info = MetaJson.objects.filter(dashboard_name=dbd_name).values(
            "dashboard_meta"
        )

    params_req = []

    if len(dbd_info) > 0:
        dbd_info = (
            dbd_info if isinstance(dbd_info, dict) else dbd_info[0]["dashboard_meta"]
        )
        params_req = dbd_info["required_params"]

    res = {}
    if all(p in param_list for p in params_req):
        data = dbd_info["charts"]

        if len(data) > 0:
            for k, v in data.items():
                api_type = v["api_type"]
                api_params = v["api_params"]
                cur_chart_data = cache.get(dbd_name + "_" + k)

                if not cur_chart_data:
                    cur_chart_data = DashboardJson.objects.filter(
                        dashboard_name=dbd_name, chart_name=k
                    ).values("chart_data")[0]["chart_data"]
                    cache.set(dbd_name + "_" + k, cur_chart_data)

                data_as_of = (
                    None
                    if "data_as_of" not in cur_chart_data
                    else cur_chart_data["data_as_of"]
                )

                if api_type == "static":
                    res[k] = {}
                    if data_as_of:
                        res[k]["data_as_of"] = data_as_of
                    res[k]["data"] = cur_chart_data["data"]
                elif api_type == "dynamic":
                    if len(api_params) > 0:
                        cur_chart_data = get_nested_data(
                            api_params, param_list, cur_chart_data["data"]
                        )

                    if len(cur_chart_data) > 0:
                        res[k] = {}
                        if data_as_of:
                            res[k]["data_as_of"] = data_as_of
                        res[k]["data"] = cur_chart_data

    return res


"""
Slices dictionary,
based on keys within dictionary
"""


def get_nested_data(api_params, param_list, data):
    for a in api_params:
        if a in param_list:
            key = (
                param_list[a][0] if "__FIXED__" not in a else a.replace("__FIXED__", "")
            )
            if key in data:
                data = data[key]
        else:
            data = {}
            break

    return data


"""
Checks whether or not,
a request made is valid
"""


def is_valid_request(request, workflow_token):
    if "Authorization" not in request.headers:
        return False

    secret = request.headers.get("Authorization")
    if secret != workflow_token:
        return False

    return True
