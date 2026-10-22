"""Native staff application catalogue, scoped permissions and registration."""
from sqlalchemy import select, delete, text, func
from native_iam_business import NativeIamBusiness, IamBusinessError, now


class NativeIamAccess(NativeIamBusiness):
    def applications_for(self, client_roles):
        client_roles={client:roles for client,roles in client_roles.items() if not roles or any(not name.startswith('__kdbt_retired_') for name in roles)}
        table=self.tables['application']
        with self.engine.connect() as c:
            rows=c.execute(select(table).where(table.c.active.is_(True)).order_by(table.c.order.asc().nullslast(),table.c.id)).mappings()
            return [{**{k:row[k] for k in ['id','application_mnemonic','application_description','icon_base64','width','order']},
                     'disabled':row['application_mnemonic'] not in client_roles,
                     'application_url':row['application_url'] if row['application_mnemonic'] in client_roles else None,
                     'api_url':row['api_url'] if row['application_mnemonic'] in client_roles else None} for row in rows]

    def permissions_for(self, client_roles, application=None):
        apps,roles,permissions,mappings=[self.tables[k] for k in ['application','role','permission','mapping']]
        result=[]
        with self.engine.connect() as c:
            for mnemonic,names in client_roles.items():
                if application and mnemonic!=application:continue
                app=c.execute(select(apps).where(apps.c.application_mnemonic==mnemonic,apps.c.active.is_(True))).mappings().first()
                if not app or not names:continue
                query=select(permissions.c.permission_mnemonic).select_from(roles.join(mappings,roles.c.id==mappings.c.role_id).join(permissions,permissions.c.id==mappings.c.permission_id)).where(
                    roles.c.application_id==app['id'],permissions.c.application_id==app['id'],roles.c.role_mnemonic.in_(names),
                    roles.c.active.is_(True),permissions.c.active.is_(True),mappings.c.active.is_(True))
                values=sorted(set(c.execute(query).scalars()))
                if values:result.append(dict(application_id=app['id'],application_mnemonic=mnemonic,permissions=values))
        return result

    def permissions_for_roles(self, names):
        roles=self.tables['role'];apps=self.tables['application'];result=set()
        with self.engine.connect() as c:
            for name in names:
                rows=c.execute(select(roles.c.application_id,apps.c.application_mnemonic).join(apps,apps.c.id==roles.c.application_id).where(roles.c.role_mnemonic==name,roles.c.active.is_(True))).mappings().all()
                if len(rows)>1:raise IamBusinessError('Ambiguous role requires application-scoped permission lookup')
                if rows:
                    for item in self.permissions_for({rows[0]['application_mnemonic']:[name]}):result.update(item['permissions'])
        return sorted(result)

    def register(self, data):
        with self.transaction() as c:
            # Seed/imported SERIAL values must not collide with fresh inserts.
            for kind in ['application','permission','role','mapping']:
                table=self.tables[kind];name=table.name
                sequence=c.execute(text('SELECT pg_get_serial_sequence(:name,\'id\')'),{'name':'public.'+name}).scalar_one()
                if sequence:
                    maximum=c.execute(select(func.max(table.c.id))).scalar() or 0
                    # nextval never rewinds an existing sequence.
                    current=c.execute(text('SELECT nextval(CAST(:sequence AS regclass))'),{'sequence':sequence}).scalar_one()
                    c.execute(text('SELECT setval(CAST(:sequence AS regclass),:value,true)'),{'sequence':sequence,'value':max(maximum,current)})
            app=self.one(c,'application',application_mnemonic=data['application_mnemonic']);created=app is None
            values={key:data.get(key) for key in ['application_url','api_url','application_description','icon_base64','width','order']}
            values.update(active=data.get('active',True),is_self_registered=True)
            app=self.put(c,'application',{**values,'application_mnemonic':data['application_mnemonic']}) if created else self.update(c,'application',app['id'],values)
            by_kind={}
            for kind,items in [('permission',data.get('permissions',[])),('role',data.get('roles',[]))]:
                names={}
                for item in items:
                    mnemonic=item[kind+'_mnemonic']
                    if mnemonic in names:raise IamBusinessError('Duplicate catalogue mnemonic')
                    row=self.one(c,kind,application_id=app['id'],**{kind+'_mnemonic':mnemonic})
                    values={kind+'_description':item.get(kind+'_description'),'active':item.get('active',True)}
                    row=self.put(c,kind,{**values,'application_id':app['id'],kind+'_mnemonic':mnemonic}) if row is None else self.update(c,kind,row['id'],values)
                    names[mnemonic]=row
                by_kind[kind]=names
            mapping=self.tables['mapping']
            for role in data.get('roles',[]):
                row=by_kind['role'][role['role_mnemonic']]
                c.execute(delete(mapping).where(mapping.c.role_id==row['id']))
                for mnemonic in dict.fromkeys(role.get('permissions',[])):
                    permission=by_kind['permission'].get(mnemonic)
                    if not permission:raise IamBusinessError('Role references a permission absent from this registration')
                    self.put(c,'mapping',dict(role_id=row['id'],permission_id=permission['id'],active=True))
            return dict(id=app['id'],application_mnemonic=app['application_mnemonic'],created=created,
                        permissions_count=len(data.get('permissions',[])),roles_count=len(data.get('roles',[])))
