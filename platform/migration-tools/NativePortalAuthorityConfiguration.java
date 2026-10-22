package org.karnatakadbt.migration;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.lang.reflect.Field;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.*;
import org.springframework.beans.factory.config.BeanPostProcessor;
import org.springframework.beans.factory.SmartInitializingSingleton;
import org.springframework.context.ApplicationContext;
import org.springframework.aop.scope.ScopedObject;
import org.springframework.util.ClassUtils;
import org.springframework.boot.autoconfigure.AutoConfiguration;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.core.env.Environment;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationConverter;
import org.springframework.security.oauth2.server.resource.authentication.JwtGrantedAuthoritiesConverter;

/** Preserve method authorization while mapping the explicitly approved portal role. */
@AutoConfiguration
@ConditionalOnProperty(name="kdbt.portal.authority.enabled", havingValue="true")
public class NativePortalAuthorityConfiguration {
    private static final String ROLE="KDBT_PORTAL_CRYPTO_ADMIN";
    private static final Set<String> ROLE_BEANS=Set.of(
        "io.mosip.kernel.signature.dto.AuthorizedRolesDTO",
        "io.mosip.kernel.cryptomanager.dto.AuthorizedRolesDTO",
        "io.mosip.kernel.keymanagerservice.dto.AuthorizedRolesDTO",
        "io.mosip.kernel.partnercertservice.dto.AuthorizedRolesDTO",
        "io.mosip.kernel.clientcrypto.dto.AuthorizedRolesDTO",
        "io.mosip.kernel.lkeymanager.dto.AuthorizedRolesDTO");

    @Bean
    public static BeanPostProcessor nativePortalMethodRoles() {
        return new BeanPostProcessor() {
            @Override public Object postProcessBeforeInitialization(Object bean,String name) {
                appendRole(bean);
                return bean;
            }
        };
    }

    private static boolean appendRole(Object value) {
        Object bean=value instanceof ScopedObject ? ((ScopedObject)value).getTargetObject() : value;
        Class<?> type=ClassUtils.getUserClass(bean);
        if (!ROLE_BEANS.contains(type.getName())) return false;
                for (Field field:type.getDeclaredFields()) {
                    if (!List.class.isAssignableFrom(field.getType())) continue;
                    try {
                        field.setAccessible(true);
                        List<?> old=(List<?>)field.get(bean);
                        List<Object> updated=new ArrayList<>();
                        if (old!=null) updated.addAll(old);
                        if (!updated.contains(ROLE)) updated.add(ROLE);
                        field.set(bean,updated);
                    } catch (ReflectiveOperationException e) {
                        throw new IllegalStateException("Portal method-role configuration failed",e);
                    }
                }
                return true;
    }

    @Bean
    public SmartInitializingSingleton nativePortalBoundMethodRoles(ApplicationContext context) {
        return () -> {
            int count=0;
            for (String name:ROLE_BEANS) {
                try {
                    Class<?> type=Class.forName(name);
                    for (Object bean:context.getBeansOfType(type).values()) if (appendRole(bean)) count++;
                } catch (ClassNotFoundException e) {
                    throw new IllegalStateException("Required crypto authority type missing",e);
                }
            }
            if (count==0) throw new IllegalStateException("No crypto method-role beans admitted");
            System.err.println("KDBT_PORTAL_AUTHORITY bound_role_beans="+count);
        };
    }

    @Bean
    public JwtAuthenticationConverter nativePortalJwtAuthenticationConverter(Environment env) {
        String issuer=env.getRequiredProperty("kdbt.portal.authority.issuer");
        String audience=env.getRequiredProperty("kdbt.portal.authority.audience");
        String client=env.getRequiredProperty("kdbt.portal.authority.role-client");
        String role=env.getRequiredProperty("kdbt.portal.authority.role");
        URI staffKeys=URI.create(env.getRequiredProperty("kdbt.portal.authority.staff-jwks"));
        StaffKeyIds trustedStaff=new StaffKeyIds(staffKeys);
        JwtGrantedAuthoritiesConverter defaults=new JwtGrantedAuthoritiesConverter();
        JwtAuthenticationConverter converter=new JwtAuthenticationConverter();
        converter.setJwtGrantedAuthoritiesConverter(jwt -> {
            Collection<GrantedAuthority> values=new ArrayList<>(defaults.convert(jwt));
            if (!issuer.equals(jwt.getClaimAsString("iss")) || jwt.getAudience()==null || !jwt.getAudience().contains(audience)) return denied(values,"issuer_or_audience");
            // A combined verifier also contains issuer credential keys. Never
            // let a credential-signing key impersonate the staff issuer.
            Object kid=jwt.getHeaders().get("kid");
            if (!(kid instanceof String) || !trustedStaff.contains((String)kid)) return denied(values,"staff_key_binding");
            Object access=jwt.getClaims().get("resource_access");
            if (!(access instanceof Map)) return denied(values,"role_container");
            Object entry=((Map<?,?>)access).get(client);
            if (!(entry instanceof Map)) return denied(values,"role_client");
            Object roles=((Map<?,?>)entry).get("roles");
            if (roles instanceof Collection && ((Collection<?>)roles).contains(role)) {
                values.add(new SimpleGrantedAuthority("ROLE_"+ROLE));
                System.err.println("KDBT_PORTAL_AUTHORITY approved_role=true");
            } else return denied(values,"administrator_role");
            return values;
        });
        return converter;
    }

    private static Collection<GrantedAuthority> denied(Collection<GrantedAuthority> values,String reason) {
        // No subject, token, key material or claim values enter diagnostics.
        System.err.println("KDBT_PORTAL_AUTHORITY approved_role=false reason="+reason);
        return values;
    }

    private static class StaffKeyIds {
        private final URI endpoint;
        private final HttpClient http=HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2))
            .followRedirects(HttpClient.Redirect.NEVER).build();
        private Set<String> kids=Set.of();
        private long refreshAfter;
        StaffKeyIds(URI endpoint) { this.endpoint=endpoint; }
        synchronized boolean contains(String kid) {
            if (System.nanoTime()>=refreshAfter) {
                try {
                    HttpResponse<String> response=http.send(HttpRequest.newBuilder(endpoint)
                        .timeout(Duration.ofSeconds(3)).GET().build(),HttpResponse.BodyHandlers.ofString());
                    if (response.statusCode()!=200 || response.body().length()>262144) return false;
                    JsonNode keys=new ObjectMapper().readTree(response.body()).get("keys");
                    if (keys==null || !keys.isArray() || keys.size()>64) return false;
                    Set<String> next=new HashSet<>();
                    for (JsonNode key:keys) {
                        if (!key.hasNonNull("kid") || key.has("d") || key.has("k") || key.has("p")) return false;
                        next.add(key.get("kid").asText());
                    }
                    kids=Set.copyOf(next);refreshAfter=System.nanoTime()+Duration.ofSeconds(30).toNanos();
                } catch (Exception e) { return false; }
            }
            return kids.contains(kid);
        }
    }
}
