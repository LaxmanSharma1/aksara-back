from aksara.catalog_utils.catalog_variable_classes.General import GeneralChartsUtil

import pandas as pd
import numpy as np
import json
from dateutil.relativedelta import relativedelta
from mergedeep import merge

class Choropleth(GeneralChartsUtil) : 
    '''Choropleth Class for choropleth variables'''
    chart_type = 'CHOROPLETH'

    # API related fields
    api_filter = []

    # Choropleth Variables
    c_parent = []
    c_format = {}
    c_color = ''
    c_file_json = ''


    '''
    Initiailize the neccessary data for a Choropleth chart
    '''
    def __init__(self, full_meta, file_data, meta_data ,variable_data, all_variable_data, file_src):
        GeneralChartsUtil.__init__(self, full_meta, file_data, meta_data ,variable_data, all_variable_data, file_src)

        self.validate_meta_json()

        self.c_color = self.meta_data['chart']['chart_variables']['color']
        self.c_file_json = self.meta_data['chart']['chart_variables']['file_json'] 
        self.c_parent = self.meta_data['chart']['chart_variables']['parents']
        self.c_format = self.meta_data['chart']['chart_variables']['format']        
        
        self.api_filter = meta_data['chart']['chart_filters']['SLICE_BY']
        self.api = self.build_api_info()

        self.chart_name = {'en' : self.variable_data['title_en'] , 'bm' : self.variable_data['title_bm']}

        self.chart_details['chart'] = self.build_chart()
        self.db_input['catalog_data'] = self.build_catalog_data_info()

    '''
    Build the Choropleth chart
    '''
    def build_chart(self) :
        df = pd.read_parquet(self.read_from)
        df = df.replace({np.nan: None})
        temp_df = ''
        res = {}
        res['CHART'] = {}
        res['TABLE'] = {}

        res['TABLE']['data'] = []
        res['TABLE']['columns'] = { 'x_en' : 'Area', 'y_en': self.chart_name['en'], 'x_bm' : 'Tempat', 'y_bm' : self.chart_name['bm']}

        parent = self.c_parent[0] if len(self.c_parent) > 0 else ''
        x = self.c_format['x']
        y = self.c_format['y']

        if parent != '' : 
            df['u_groups'] = list(df[[parent]].itertuples(index=False, name=None))
            u_groups_list = df['u_groups'].unique().tolist()

            for u in u_groups_list : 
                temp_df = df.groupby(parent).get_group(u[0])[ [x, y] ]
                temp_df = df[ [x, y] ].rename(columns={x : 'id', y : 'value'})
                res['CHART'][u[0]] = temp_df.to_dict('records')
                res['TABLE']['data'][u[0]] = temp_df.rename(columns={'id' : 'x', 'value' : 'y'}).to_dict('records')
        else : 
            temp_df = df[ [x, y] ].rename(columns={x : 'id', y : 'value'})
            res['CHART'] = temp_df.to_dict('records')
            res['TABLE']['data'] = temp_df.rename(columns={'id' : 'x', 'value' : 'y'}).to_dict('records')

        return res 

    '''
    Builds the API info for Choropleth
    '''
    def build_api_info(self) : 
        res = {}

        res['API'] = {}
        res['API']['chart_type'] = self.meta_data['chart']['chart_type']
        res['API']['color'] = self.c_color
        res['API']['file_json'] = self.c_file_json

        if self.api_filter : 
            df = pd.read_parquet(self.read_from)
            fe_vals = df[self.api_filter].unique().tolist()
            be_vals = df[self.api_filter].apply(lambda x : x.lower().replace(' ', '-')).unique().tolist()
            filter_obj = self.build_api_object_filter('filter', fe_vals[0], be_vals[0], dict(zip(fe_vals, be_vals)))
            res['API']['filters'] = [filter_obj]
    
        return res['API']

    def validate_meta_json(self) :
        src = self.variable_name

        self.validate_field_presence(["id", "name", "title_en", "title_bm", "desc_en", "desc_bm"], src, self.variable_data)
        s = {'int' : ["id"], 'str' : ["name", "title_en", "title_bm", "desc_en", "desc_bm"]}
        self.validate_data_type(s, src, self.variable_data)

        self.validate_field_presence(["id", "catalog_filters", "metadata_neutral", "metadata_lang", "chart"], src, self.meta_data)
        s = {'int' : ['id'], 'dict' : ["catalog_filters", "metadata_neutral", "metadata_lang", "chart"] }
        self.validate_data_type(s, src, self.meta_data)

        self.validate_field_presence(["frequency", "geographic", "start", "end", "data_source"], src, self.meta_data['catalog_filters'])
        s = {"str" : ["frequency"], "list" : ["geographic", "data_source"]}
        self.validate_data_type(s, src, self.meta_data['catalog_filters'])

        self.validate_field_presence(["data_as_of", "last_updated", "next_update"], src, self.meta_data['metadata_neutral'])
        s = {"str" : ["data_as_of", "last_updated", "next_update"]}
        self.validate_data_type(s, src, self.meta_data['metadata_neutral'])

        self.validate_field_presence(["methodology", "caveat"], src, self.meta_data['metadata_lang']['en'])
        self.validate_field_presence(["methodology", "caveat"], src, self.meta_data['metadata_lang']['bm'])
        s = {"str" : ["methodology", "caveat"]}
        self.validate_data_type(s, src, self.meta_data['metadata_lang']['en'])
        self.validate_data_type(s, src, self.meta_data['metadata_lang']['bm'])

        self.validate_field_presence(["chart_type", "chart_filters", "chart_variables"], src, self.meta_data['chart'])
        s = {"str" : ["chart_type"]}
        self.validate_data_type(s, src, self.meta_data['chart'])

        self.validate_field_presence(["SLICE_BY"], src, self.meta_data['chart']['chart_filters'])
        s = {"list" : ["SLICE_BY"]}
        self.validate_data_type(s, src, self.meta_data['chart']['chart_filters'])

        self.validate_field_presence(["parents", "color", "file_json", "format"], src, self.meta_data['chart']['chart_variables'])
        s = {"str" : ["color", "file_json"], "list" : ["parents"], "dict" : ["format"]}
        self.validate_data_type(s, src, self.meta_data['chart']['chart_variables'])

        self.validate_field_presence(["x", "y"], src, self.meta_data["chart"]["chart_variables"]["format"])
        s = {"str" : ["x", "y"]}
        self.validate_data_type(s, src, self.meta_data["chart"]["chart_variables"]["format"])